"""
incident_agent/mcp_server.py
----------------------------
Step 3 project addition: the six incident-investigator tools exposed behind a
FastMCP server (Streamable HTTP / stdio), reusing the repository's zero-trust
gateway conventions (strict Pydantic request models, fail-closed RBAC, rate
limiting, token circuit breaker, per-tool tracing).

The tools are read-only (least privilege). Remediation is NOT exposed here —
it lives behind the approval gate in :mod:`incident_agent.guardrails`.
"""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

from fastmcp import FastMCP
from pydantic import BaseModel, ConfigDict, Field

from agent.guardrails import SlidingWindowRateLimiter, TokenCircuitBreaker
from incident_agent.tools import IncidentToolRegistry

mcp = FastMCP("Incident-Investigator")

# Gateway blast-radius controls (same defaults as the SDLC gateway).
_rate_limiter = SlidingWindowRateLimiter(
    max_requests=int(os.getenv("INCIDENT_MCP_RATE_LIMIT_MAX_REQUESTS", "60")),
    window_seconds=float(os.getenv("INCIDENT_MCP_RATE_LIMIT_WINDOW_SECONDS", "60")),
)
_token_breaker = TokenCircuitBreaker(
    max_tokens_per_request=int(os.getenv("INCIDENT_MCP_MAX_TOKENS_PER_REQUEST", "8000")),
    max_tokens_per_issue=int(os.getenv("INCIDENT_MCP_MAX_TOKENS_PER_ISSUE", "20000")),
)

# Read-only least-privilege tool ACL.
TOOL_REQUIRED_ROLES: Dict[str, List[str]] = {
    "incident.get": ["engineer", "sre", "admin"],
    "incident.list": ["engineer", "sre", "admin"],
    "logs.query": ["engineer", "sre", "admin"],
    "metrics.query": ["engineer", "sre", "admin"],
    "changes.list": ["engineer", "sre", "admin"],
    "memory.recall_similar": ["engineer", "sre", "admin"],
}

_registry = IncidentToolRegistry()


class _BaseRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    auth_token: Optional[str] = Field(default=None, description="Optional caller token.")
    user_roles: Optional[List[str]] = Field(
        default=None, description="Fallback roles when auth is disabled."
    )


class IncidentGetRequest(_BaseRequest):
    incident_id: str = Field(min_length=1)


class IncidentListRequest(_BaseRequest):
    pass


class LogsQueryRequest(_BaseRequest):
    service: str = Field(min_length=1)
    since_minutes: int = Field(default=120, ge=1, le=1440)
    level: Optional[str] = None


class MetricsQueryRequest(_BaseRequest):
    service: str = Field(min_length=1)
    metric: Optional[str] = None


class ChangesListRequest(_BaseRequest):
    service: str = Field(min_length=1)
    last_n: int = Field(default=10, ge=1, le=50)


class MemoryRecallRequest(_BaseRequest):
    incident_id: str = Field(min_length=1)
    top_k: int = Field(default=3, ge=1, le=10)


def _resolve_roles(req: _BaseRequest) -> List[str]:
    if req.user_roles:
        return req.user_roles
    return ["engineer"]


def _check_acl(tool_name: str, roles: List[str]) -> Optional[str]:
    required = TOOL_REQUIRED_ROLES.get(tool_name, [])
    if not required or "*" in required:
        return None
    if not roles:
        return (
            f"Tool authorization error: '{tool_name}' requires one of "
            f"{required}; caller resolved to no roles."
        )
    if any(r in required for r in roles):
        return None
    return (
        f"Tool authorization error: '{tool_name}' requires one of "
        f"{required}; caller roles: {roles}."
    )


async def _guarded_dispatch(tool_name: str, request: _BaseRequest, arguments: Dict[str, Any]) -> str:
    """Rate limit -> token budget -> RBAC -> dispatch, mirroring the SDLC gateway."""
    import json
    import time

    from incident_agent.tools import ToolResult  # local import to avoid cycles

    t0 = time.perf_counter()
    roles = _resolve_roles(request)

    allowed_rate, _remaining, _retry = _rate_limiter.allow_request(
        f"incident:{roles[0] if roles else 'anon'}"
    )
    if not allowed_rate:
        return f"⛔ Rate limit exceeded for incident investigator caller."

    est_tokens = TokenCircuitBreaker.estimate_tokens(json.dumps(arguments))
    allowed_tokens, _rem, _tok_err = _token_breaker.check_and_consume(
        "incident-investigator", est_tokens
    )
    if not allowed_tokens:
        return "⛔ Token budget exceeded for incident investigator."

    acl_err = _check_acl(tool_name, roles)
    if acl_err:
        return f"⛔ {acl_err}"

    result: ToolResult = await _registry.dispatch(tool_name, arguments)
    duration_ms = round((time.perf_counter() - t0) * 1000, 2)
    payload = result.to_compact_text()
    return json.dumps(
        {
            "tool": tool_name,
            "ok": result.ok,
            "duration_ms": duration_ms,
            "result": payload,
        },
        default=str,
    )


@mcp.tool()
async def incident_get(request: IncidentGetRequest) -> str:
    """Fetch one incident's alert metadata by incident_id."""
    return await _guarded_dispatch(
        "incident.get", request, {"incident_id": request.incident_id}
    )


@mcp.tool()
async def incident_list(request: IncidentListRequest) -> str:
    """List all open incidents with id, service, and severity."""
    return await _guarded_dispatch("incident.list", request, {})


@mcp.tool()
async def logs_query(request: LogsQueryRequest) -> str:
    """Query structured logs for a service within a lookback window."""
    return await _guarded_dispatch(
        "logs.query",
        request,
        {
            "service": request.service,
            "since_minutes": request.since_minutes,
            "level": request.level,
        },
    )


@mcp.tool()
async def metrics_query(request: MetricsQueryRequest) -> str:
    """Query time-series metrics for a service, optionally by metric name."""
    return await _guarded_dispatch(
        "metrics.query", request, {"service": request.service, "metric": request.metric}
    )


@mcp.tool()
async def changes_list(request: ChangesListRequest) -> str:
    """List recent change events (deploy/config/schema/infra) for a service."""
    return await _guarded_dispatch(
        "changes.list", request, {"service": request.service, "last_n": request.last_n}
    )


@mcp.tool()
async def memory_recall_similar(request: MemoryRecallRequest) -> str:
    """Recall previously solved incidents similar to this one from long-term memory."""
    return await _guarded_dispatch(
        "memory.recall_similar",
        request,
        {"incident_id": request.incident_id, "top_k": request.top_k},
    )


def run_server(
    transport: Optional[str] = None,
    host: Optional[str] = None,
    port: Optional[int] = None,
) -> None:
    """Run the incident-investigator FastMCP server (http/streamable-http/stdio)."""
    import argparse

    parser = argparse.ArgumentParser(description="Incident Investigator FastMCP server")
    parser.add_argument(
        "--transport",
        choices=["stdio", "sse", "http", "streamable-http"],
        default=os.getenv("INCIDENT_MCP_TRANSPORT", "stdio"),
    )
    parser.add_argument("--host", default=os.getenv("INCIDENT_MCP_HOST", "127.0.0.1"))
    parser.add_argument(
        "--port", type=int, default=int(os.getenv("INCIDENT_MCP_PORT", "8001"))
    )
    args, _ = parser.parse_known_args()

    selected_transport = (transport or args.transport or "stdio").lower()
    selected_host = host or args.host
    selected_port = port or args.port

    if selected_transport in ("sse", "http", "streamable-http"):
        mcp.run(
            transport=selected_transport, host=selected_host, port=selected_port
        )
    else:
        mcp.run(transport="stdio")


if __name__ == "__main__":
    run_server()
