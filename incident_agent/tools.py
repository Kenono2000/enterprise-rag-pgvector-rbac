"""
incident_agent/tools.py
-----------------------
Tool contracts for the incident investigator (Step 3 of the roadmap).

Design rules applied from the article:
- One purpose per tool, domain-based naming (``incident.*`` / ``logs.*`` /
  ``metrics.*`` / ``changes.*`` / ``memory.*``).
- Compact outputs with explicit truncation markers so the context window is
  never silently flooded.
- Actionable error messages that tell the caller how to fix the invocation.
- Read-only least privilege: every tool here is a query; nothing mutates.
"""

from __future__ import annotations

import json
import time
from typing import Any, Callable, Dict, List, Optional

from pydantic import BaseModel, ConfigDict

from incident_agent import data
from incident_agent.models import ChangeEvent, Incident, LogEntry, MetricPoint

MAX_OUTPUT_CHARS = 1200  # compact-output contract
TRUNCATION_MARKER = "...[truncated]"


def _truncate(text: str, limit: int = MAX_OUTPUT_CHARS) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - len(TRUNCATION_MARKER)] + TRUNCATION_MARKER


def _dumps(obj: Any) -> str:
    return json.dumps(obj, default=str, sort_keys=True)


# ---------------------------------------------------------------------------
# Individual tool implementations (read-only queries over the synthetic corpus)
# ---------------------------------------------------------------------------


def tool_get_incident(incident_id: str) -> Dict[str, Any]:
    """Fetch one incident's alert metadata by id."""
    if not incident_id or not str(incident_id).strip():
        raise ValueError("incident_id is required; pass a non-empty string such as 'INC-1001'.")
    try:
        rec = data.get_incident(str(incident_id).strip())
    except KeyError:
        raise ValueError(
            f"Unknown incident_id '{incident_id}'. List known ids with incident.list_ids()."
        )
    inc: Incident = rec["incident"]
    return {
        "incident_id": inc.incident_id,
        "service": inc.service,
        "title": inc.title,
        "severity": inc.severity.value,
        "status": inc.status.value,
        "alert_fired_at": inc.alert_fired_at.isoformat(),
        "summary": inc.summary,
        "runbook_hint": inc.runbook_hint,
    }


def tool_list_incidents() -> Dict[str, Any]:
    """List all open incidents (id, service, severity)."""
    rows = [
        {
            "incident_id": rec["incident"].incident_id,
            "service": rec["incident"].service,
            "severity": rec["incident"].severity.value,
        }
        for rec in data.INCIDENTS
    ]
    return {"count": len(rows), "incidents": rows}


def tool_query_logs(service: str, since_minutes: int = 120, level: Optional[str] = None) -> Dict[str, Any]:
    """Query structured logs for a service within a lookback window."""
    if not service or not str(service).strip():
        raise ValueError("service is required; pass e.g. 'svc-payments'.")
    service = str(service).strip()
    known = sorted(set(c.service for c in _all_changes()))
    if service not in known:
        raise ValueError(f"Unknown service '{service}'. Known services: {', '.join(known)}.")
    # Deterministic corpus clock: the synthetic corpus is anchored at a fixed
    # base time, so the lookback window is reproducible across replay runs.
    from datetime import timedelta
    since = data.BASE_TIME - timedelta(minutes=int(since_minutes))
    entries: List[LogEntry] = data.logs_for(service, since=since)
    if level:
        entries = [e for e in entries if e.level.upper() == str(level).upper()]
    rows = [
        {"ts": e.timestamp.isoformat(), "level": e.level, "message": e.message}
        for e in entries
    ]
    return {"service": service, "count": len(rows), "logs": rows}


def tool_query_metrics(service: str, metric: Optional[str] = None) -> Dict[str, Any]:
    """Query time-series metrics for a service, optionally filtered by metric name."""
    if not service or not str(service).strip():
        raise ValueError("service is required; pass e.g. 'svc-search'.")
    service = str(service).strip()
    known = sorted(set(c.service for c in _all_changes()))
    if service not in known:
        raise ValueError(f"Unknown service '{service}'. Known services: {', '.join(known)}.")
    points: List[MetricPoint] = data.metrics_for(service, metric)
    rows = [
        {"ts": p.timestamp.isoformat(), "metric": p.metric, "value": p.value}
        for p in points
    ]
    return {"service": service, "metric_filter": metric, "count": len(rows), "metrics": rows}


def tool_list_changes(service: str, last_n: int = 10) -> Dict[str, Any]:
    """List recent change events (deploys/config/schema/infra) for a service."""
    if not service or not str(service).strip():
        raise ValueError("service is required; pass e.g. 'svc-cart'.")
    service = str(service).strip()
    known = sorted(set(c.service for c in _all_changes()))
    if service not in known:
        raise ValueError(f"Unknown service '{service}'. Known services: {', '.join(known)}.")
    changes: List[ChangeEvent] = data.changes_for(service)[-int(last_n):]
    rows = [
        {
            "change_id": c.change_id,
            "ts": c.timestamp.isoformat(),
            "kind": c.kind,
            "actor": c.actor,
            "description": c.description,
        }
        for c in changes
    ]
    return {"service": service, "count": len(rows), "changes": rows}


def tool_recall_similar_incidents(incident_id: str, top_k: int = 3) -> Dict[str, Any]:
    """Recall previously solved incidents similar to this one from long-term memory."""
    from incident_agent.memory import IncidentMemory
    try:
        rec = data.get_incident(str(incident_id).strip())
    except KeyError:
        raise ValueError(
            f"Unknown incident_id '{incident_id}'. List known ids with incident.list_ids()."
        )
    memory = IncidentMemory()
    hits = memory.retrieve_similar(rec["incident"].service, rec["incident"].title, top_k=int(top_k))
    return {"incident_id": rec["incident"].incident_id, "similar": hits}


def _all_changes() -> List[ChangeEvent]:
    out: List[ChangeEvent] = []
    for evs in data.CHANGES.values():
        out.extend(evs)
    return out


# ---------------------------------------------------------------------------
# Registry + dispatcher
# ---------------------------------------------------------------------------

TOOL_SPECS: Dict[str, Dict[str, Any]] = {
    "incident.get": {
        "description": "Fetch one incident's alert metadata by incident_id.",
        "parameters": {"incident_id": "str, required, e.g. 'INC-1001'"},
        "handler": tool_get_incident,
    },
    "incident.list": {
        "description": "List all open incidents with id, service, and severity.",
        "parameters": {},
        "handler": tool_list_incidents,
    },
    "logs.query": {
        "description": "Query structured logs for a service within a lookback window.",
        "parameters": {
            "service": "str, required, e.g. 'svc-payments'",
            "since_minutes": "int, optional (default 120)",
            "level": "str, optional filter (INFO/WARN/ERROR)",
        },
        "handler": tool_query_logs,
    },
    "metrics.query": {
        "description": "Query time-series metrics for a service, optionally by metric name.",
        "parameters": {
            "service": "str, required",
            "metric": "str, optional metric name filter",
        },
        "handler": tool_query_metrics,
    },
    "changes.list": {
        "description": "List recent change events (deploy/config/schema/infra) for a service.",
        "parameters": {"service": "str, required", "last_n": "int, optional (default 10)"},
        "handler": tool_list_changes,
    },
    "memory.recall_similar": {
        "description": "Recall previously solved incidents similar to this one from long-term memory.",
        "parameters": {"incident_id": "str, required", "top_k": "int, optional (default 3)"},
        "handler": tool_recall_similar_incidents,
    },
}


class ToolResult(BaseModel):
    """Uniform tool return: ok flag, compact payload, and actionable error."""

    model_config = ConfigDict(extra="forbid")

    tool: str
    ok: bool
    payload: Any = None
    error: Optional[str] = None
    duration_ms: float = 0.0

    def to_compact_text(self) -> str:
        if not self.ok:
            return f"[TOOL ERROR {self.tool}] {self.error}"
        return _truncate(_dumps(self.payload))


class IncidentToolRegistry:
    """
    Tool registry + dispatcher. Tools are contracts: one purpose each,
    domain-named, compact outputs, actionable errors. The MCP server and the
    agent loop both dispatch through this single registry so the contract is
    enforced in exactly one place.
    """

    def __init__(self, tools: Optional[Dict[str, Dict[str, Any]]] = None):
        self._tools = tools if tools is not None else TOOL_SPECS

    @property
    def tool_names(self) -> List[str]:
        return sorted(self._tools.keys())

    def describe(self) -> List[Dict[str, Any]]:
        return [
            {"name": name, **spec} for name, spec in sorted(self._tools.items())
        ]

    async def dispatch(self, tool_name: str, arguments: Dict[str, Any]) -> ToolResult:
        spec = self._tools.get(tool_name)
        if spec is None:
            return ToolResult(
                tool=tool_name, ok=False,
                error=(
                    f"Unknown tool '{tool_name}'. Available tools: "
                    f"{', '.join(sorted(self._tools))}. Fix the tool name and retry."
                ),
            )
        handler: Callable[..., Any] = spec["handler"]
        t0 = time.perf_counter()
        try:
            payload = handler(**(arguments or {}))
        except TypeError as exc:
            return ToolResult(
                tool=tool_name, ok=False, duration_ms=(time.perf_counter() - t0) * 1000,
                error=(
                    f"Bad arguments for '{tool_name}': {exc}. "
                    f"Expected parameters: {json.dumps(spec['parameters'])}. "
                    "Pass only the documented parameters."
                ),
            )
        except ValueError as exc:
            return ToolResult(
                tool=tool_name, ok=False, duration_ms=(time.perf_counter() - t0) * 1000,
                error=f"Invalid input for '{tool_name}': {exc}",
            )
        except Exception as exc:  # noqa: BLE001 - tool boundary must never raise
            return ToolResult(
                tool=tool_name, ok=False, duration_ms=(time.perf_counter() - t0) * 1000,
                error=f"Tool '{tool_name}' failed unexpectedly: {type(exc).__name__}: {exc}",
            )
        return ToolResult(
            tool=tool_name, ok=True, payload=payload,
            duration_ms=(time.perf_counter() - t0) * 1000,
        )
