import os
import sys
import json
import logging
import time
from pathlib import Path
from typing import Optional, List, Tuple, Dict, Any

# Add the project root to sys.path to allow absolute imports of the 'app' package
# when this file is run as a standalone script (e.g., by fastmcp inspect).
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from dotenv import load_dotenv, find_dotenv
load_dotenv(find_dotenv(), override=True)

from pydantic import BaseModel, ConfigDict, Field
from fastmcp import FastMCP
from app.db.manager import DatabaseManager
from app.db.llm import generate_embedding, chat_completion
from app.auth.jwks import verify_google_token
from app.auth.role_mapper import extract_roles
from app.observability import tracer
from agent.guardrails import SlidingWindowRateLimiter, TokenCircuitBreaker

logger = logging.getLogger(__name__)

mcp = FastMCP("SDLC-Harness-Gateway")

# Gateway-level blast-radius controls
mcp_rate_limiter = SlidingWindowRateLimiter(
    max_requests=int(os.getenv("MCP_RATE_LIMIT_MAX_REQUESTS", "60")),
    window_seconds=float(os.getenv("MCP_RATE_LIMIT_WINDOW_SECONDS", "60")),
)
mcp_token_breaker = TokenCircuitBreaker(
    max_tokens_per_request=int(os.getenv("MCP_MAX_TOKENS_PER_REQUEST", "8000")),
    max_tokens_per_issue=int(os.getenv("MCP_MAX_TOKENS_PER_ISSUE", "50000")),
)

# Tool-level Role-Based Access Control (ACL) mapping to prevent confused deputy exploits (RFC 8707)
TOOL_REQUIRED_ROLES: Dict[str, List[str]] = {
    "search_sdlc_context": ["engineer", "compliance_auditor", "finance_executive", "admin", "executive"],
    "list_documents": ["engineer", "compliance_auditor", "finance_executive", "admin", "executive"],
    "propose_patch": ["engineer", "admin"],
    "run_sdlc_crew": ["engineer", "admin"],
    "recall_hermes_skills": ["engineer", "compliance_auditor", "finance_executive", "admin", "executive"],
    "get_gateway_metadata": ["engineer", "compliance_auditor", "finance_executive", "admin", "executive"],
}


# ---------------------------------------------------------------------------
# Strict Deterministic Pydantic Tool Schemas (extra='forbid')
# ---------------------------------------------------------------------------

class MCPSearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str = Field(..., min_length=1, description="Natural language search query.")
    auth_token: Optional[str] = Field(default=None, description="Google OAuth ID token.")
    user_roles: Optional[List[str]] = Field(default=None, description="Fallback roles when REQUIRE_GOOGLE_AUTH=false.")


class MCPPatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    branch_name: str = Field(..., min_length=1, description="Target git branch name.")
    patch_content: str = Field(..., min_length=1, description="Unified diff or file patch content.")
    auth_token: Optional[str] = Field(default=None, description="Google OAuth ID token.")


class MCPSDLCCrewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    issue_title: str = Field(..., min_length=1, description="GitHub issue title for the CrewAI SDLC crew.")
    issue_description: str = Field(default="", description="Detailed issue body or reproduction steps.")
    auth_token: Optional[str] = Field(default=None, description="Google OAuth ID token.")


class MCPHermesSkillRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(..., min_length=1, description="Search query to recall matching Hermes SKILL.md playbooks.")
    max_skills: int = Field(default=2, ge=1, le=10, description="Maximum number of skills to recall.")
    auth_token: Optional[str] = Field(default=None, description="Google OAuth ID token.")


class MCPListDocumentsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    limit: int = Field(default=20, ge=1, le=100, description="Maximum number of documents to return.")
    auth_token: Optional[str] = Field(default=None, description="Google OAuth ID token.")
    user_roles: Optional[List[str]] = Field(default=None, description="Fallback roles when REQUIRE_GOOGLE_AUTH=false.")


def _resolve_tool_roles(
    auth_token: Optional[str] = None,
    user_roles: Optional[List[str]] = None,
) -> Tuple[Optional[List[str]], Optional[str]]:
    """
    Resolve and verify application roles for an MCP tool invocation.

    Returns:
        (roles, error_message)
    """
    require_google = os.getenv("REQUIRE_GOOGLE_AUTH", "false").lower() == "true"

    if auth_token:
        try:
            payload = verify_google_token(auth_token)
            roles = extract_roles(payload)
            logger.info("MCP authenticated sub=%s roles=%s", payload.get("sub"), roles)
            return roles, None
        except Exception as exc:
            logger.warning("MCP token verification failed: %s", exc)
            return None, f"Token verification failed: {str(exc)}"

    if require_google:
        return None, "Authorization required: provide a valid Google ID token via 'auth_token'."

    # Dev/testing fallback when REQUIRE_GOOGLE_AUTH=false
    fallback_roles = user_roles if user_roles is not None else ["finance_executive"]
    logger.debug("MCP unauthenticated fallback using roles: %s", fallback_roles)
    return fallback_roles, None


def check_tool_permission(tool_name: str, roles: Optional[List[str]]) -> Tuple[bool, Optional[str]]:
    """
    Enforce tool-level Role-Based Access Control (ACL) to block confused deputy exploits (RFC 8707).
    """
    if roles is None or not roles:
        return True, None
    required = TOOL_REQUIRED_ROLES.get(tool_name)
    if not required or "*" in required:
        return True, None
    if any(r in required for r in roles):
        return True, None
    return False, f"Tool authorization error: Tool '{tool_name}' requires one of {required}. Current roles: {roles}"


def _resolve_caller_attribution(auth_token: Optional[str] = None) -> Dict[str, str]:
    """Extract deterministic caller attribution metadata (`sub`, `email`) for audit spans."""
    if auth_token:
        try:
            payload = verify_google_token(auth_token)
            return {
                "caller_sub": str(payload.get("sub") or payload.get("email") or "authenticated-user"),
                "caller_email": str(payload.get("email") or "unknown"),
            }
        except Exception:
            pass
    return {"caller_sub": "anonymous", "caller_email": "anonymous"}


@mcp.tool()
async def search_sdlc_context(
    question: str,
    auth_token: Optional[str] = None,
    user_roles: Optional[list[str]] = None,
) -> str:
    """
    Search the knowledge base for SDLC context (ADRs, standards, policies).

    Parameters:
    - question: Natural language question or search query.
    - auth_token: Optional Google ID token. If supplied, application roles are cryptographically
      verified via Google JWKS.
    - user_roles: Optional fallback roles list (only honored if REQUIRE_GOOGLE_AUTH=false).
    """
    t_start = time.perf_counter()
    validated = MCPSearchRequest(
        question=question,
        auth_token=auth_token,
        user_roles=user_roles,
    )
    roles, error = _resolve_tool_roles(validated.auth_token, validated.user_roles)
    attribution = _resolve_caller_attribution(validated.auth_token)
    caller_key = attribution["caller_sub"]

    if error:
        duration_ms = round((time.perf_counter() - t_start) * 1000, 2)
        res = f"⛔ {error}"
        tracer.record_mcp_tool_execution(
            tool_name="search_sdlc_context",
            parameters={"question": validated.question, **attribution},
            result=res,
            roles=roles,
            duration_ms=duration_ms,
            error=error,
        )
        return res

    allowed_acl, acl_err = check_tool_permission("search_sdlc_context", roles)
    if not allowed_acl:
        duration_ms = round((time.perf_counter() - t_start) * 1000, 2)
        res = f"⛔ {acl_err}"
        tracer.record_mcp_tool_execution(
            tool_name="search_sdlc_context",
            parameters={"question": validated.question, **attribution},
            result=res,
            roles=roles,
            duration_ms=duration_ms,
            error=acl_err,
        )
        return res

    allowed_rate, remaining_reqs, retry_after = mcp_rate_limiter.allow_request(caller_key)
    if not allowed_rate:
        duration_ms = round((time.perf_counter() - t_start) * 1000, 2)
        err = f"Rate limit exceeded for caller '{caller_key}'. Retry after {retry_after}s."
        res = f"⛔ {err}"
        tracer.record_mcp_tool_execution(
            tool_name="search_sdlc_context",
            parameters={"question": validated.question, **attribution},
            result=res,
            roles=roles,
            duration_ms=duration_ms,
            error=err,
        )
        return res

    estimated_req_tokens = TokenCircuitBreaker.estimate_tokens(validated.question)
    allowed_tokens, remaining_tokens, token_err = mcp_token_breaker.check_and_consume(
        caller_key, estimated_req_tokens
    )
    if not allowed_tokens:
        duration_ms = round((time.perf_counter() - t_start) * 1000, 2)
        res = f"⛔ {token_err}"
        tracer.record_mcp_tool_execution(
            tool_name="search_sdlc_context",
            parameters={"question": validated.question, **attribution},
            result=res,
            roles=roles,
            duration_ms=duration_ms,
            error=token_err,
        )
        return res

    query_vector = await generate_embedding(validated.question)

    backend = os.getenv("RETRIEVAL_BACKEND", "").lower()
    if backend == "azure":
        from app.db.azure_search import azure_hybrid_search
        rows = await azure_hybrid_search(validated.question, query_vector, roles, limit=3)
    elif backend in ("gcp", "google_cloud", "vertex"):
        from app.db.gcp_search import gcp_hybrid_search
        rows = await gcp_hybrid_search(validated.question, query_vector, roles, limit=3)
    elif backend in ("databricks", "databrick"):
        from app.db.databricks_search import databricks_hybrid_search
        rows = await databricks_hybrid_search(validated.question, query_vector, roles, limit=3)
    else:
        rows = await DatabaseManager.secure_search(query_vector, roles)

    if not rows:
        duration_ms = round((time.perf_counter() - t_start) * 1000, 2)
        res = f"No authorized documentation found for the evaluated roles: {roles}"
        tracer.record_mcp_tool_execution(
            tool_name="search_sdlc_context",
            parameters={
                "question": validated.question,
                "rate_limit_remaining": remaining_reqs,
                "token_budget_remaining": remaining_tokens,
                **attribution,
            },
            result=res,
            roles=roles,
            duration_ms=duration_ms,
        )
        return res

    context_chunks = "\n\n".join([f"[{r['title']}]: {r['content']}" for r in rows])

    prompt = f"Answer strictly using context:\n\n{context_chunks}\n\nQuestion: {validated.question}"
    answer_text = await chat_completion(prompt)

    citations = [f"- {r['title']} (similarity: {round(float(r['similarity']), 3)})" for r in rows]
    citations_text = "\n".join(citations)

    result_text = f"{answer_text}\n\nCitations:\n{citations_text}\n\n[Authorized Roles Evaluated: {roles}]"
    duration_ms = round((time.perf_counter() - t_start) * 1000, 2)
    tracer.record_mcp_tool_execution(
        tool_name="search_sdlc_context",
        parameters={
            "question": validated.question,
            "rate_limit_remaining": remaining_reqs,
            "token_budget_remaining": remaining_tokens,
            **attribution,
        },
        result=result_text,
        roles=roles,
        duration_ms=duration_ms,
    )
    return result_text


@mcp.tool()
async def propose_patch(
    branch_name: str,
    patch_content: str,
    auth_token: Optional[str] = None,
) -> str:
    """
    Submit a code patch for review.

    Parameters:
    - branch_name: Target git branch name.
    - patch_content: The patch content.
    - auth_token: Optional Google ID token to verify submitter identity.
    """
    t_start = time.perf_counter()
    validated = MCPPatchRequest(
        branch_name=branch_name,
        patch_content=patch_content,
        auth_token=auth_token,
    )
    submitter = "anonymous"
    if validated.auth_token:
        try:
            payload = verify_google_token(validated.auth_token)
            submitter = payload.get("email") or payload.get("sub", "authenticated-user")
            caller_roles = extract_roles(payload)
            allowed_acl, acl_err = check_tool_permission("propose_patch", caller_roles)
            if not allowed_acl:
                duration_ms = round((time.perf_counter() - t_start) * 1000, 2)
                err_msg = f"⛔ {acl_err}"
                tracer.record_mcp_tool_execution(
                    tool_name="propose_patch",
                    parameters={"branch_name": validated.branch_name, "caller_sub": submitter},
                    result=err_msg,
                    roles=caller_roles,
                    duration_ms=duration_ms,
                    error=acl_err,
                )
                return err_msg
        except Exception as exc:
            duration_ms = round((time.perf_counter() - t_start) * 1000, 2)
            err_msg = f"⛔ Authentication failed: {str(exc)}"
            tracer.record_mcp_tool_execution(
                tool_name="propose_patch",
                parameters={"branch_name": validated.branch_name, "caller_sub": submitter},
                result=err_msg,
                roles=None,
                duration_ms=duration_ms,
                error=str(exc),
            )
            return err_msg
    elif os.getenv("REQUIRE_GOOGLE_AUTH", "false").lower() == "true":
        duration_ms = round((time.perf_counter() - t_start) * 1000, 2)
        err_msg = "⛔ Authorization required: provide a valid Google ID token via 'auth_token'."
        tracer.record_mcp_tool_execution(
            tool_name="propose_patch",
            parameters={"branch_name": validated.branch_name, "caller_sub": submitter},
            result=err_msg,
            roles=None,
            duration_ms=duration_ms,
            error="Unauthorized",
        )
        return err_msg

    allowed_rate, remaining_reqs, retry_after = mcp_rate_limiter.allow_request(submitter)
    if not allowed_rate:
        duration_ms = round((time.perf_counter() - t_start) * 1000, 2)
        err_msg = f"⛔ Rate limit exceeded for caller '{submitter}'. Retry after {retry_after}s."
        tracer.record_mcp_tool_execution(
            tool_name="propose_patch",
            parameters={"branch_name": validated.branch_name, "caller_sub": submitter},
            result=err_msg,
            roles=[submitter],
            duration_ms=duration_ms,
            error="RateLimitExceeded",
        )
        return err_msg

    patch_tokens = TokenCircuitBreaker.estimate_tokens(validated.patch_content)
    allowed_tokens, remaining_tokens, token_err = mcp_token_breaker.check_and_consume(
        submitter, patch_tokens
    )
    if not allowed_tokens:
        duration_ms = round((time.perf_counter() - t_start) * 1000, 2)
        err_msg = f"⛔ {token_err}"
        tracer.record_mcp_tool_execution(
            tool_name="propose_patch",
            parameters={"branch_name": validated.branch_name, "caller_sub": submitter},
            result=err_msg,
            roles=[submitter],
            duration_ms=duration_ms,
            error=token_err,
        )
        return err_msg

    res = f"Patch submitted to {validated.branch_name} by {submitter}"
    duration_ms = round((time.perf_counter() - t_start) * 1000, 2)
    tracer.record_mcp_tool_execution(
        tool_name="propose_patch",
        parameters={
            "branch_name": validated.branch_name,
            "caller_sub": submitter,
            "rate_limit_remaining": remaining_reqs,
            "token_budget_remaining": remaining_tokens,
        },
        result=res,
        roles=[submitter],
        duration_ms=duration_ms,
    )
    return res


@mcp.tool()
async def run_sdlc_crew(
    issue_title: str,
    issue_description: str = "",
    auth_token: Optional[str] = None,
) -> str:
    """
    Assemble and kick off the CrewAI SDLC multi-agent crew (`Architect -> Auditor -> Triager`)
    with automatic Hermes skill recall over FastMCP.
    """
    from agent.workflow import SDLCCrewOrchestrator, HermesSkillSynthesizer

    t_start = time.perf_counter()
    validated = MCPSDLCCrewRequest(
        issue_title=issue_title,
        issue_description=issue_description,
        auth_token=auth_token,
    )
    roles, error = _resolve_tool_roles(validated.auth_token)
    attribution = _resolve_caller_attribution(validated.auth_token)
    caller_key = attribution["caller_sub"]

    if error:
        duration_ms = round((time.perf_counter() - t_start) * 1000, 2)
        res = f"⛔ {error}"
        tracer.record_mcp_tool_execution(
            tool_name="run_sdlc_crew",
            parameters={"issue_title": validated.issue_title, **attribution},
            result=res,
            roles=roles,
            duration_ms=duration_ms,
            error=error,
        )
        return res

    allowed_acl, acl_err = check_tool_permission("run_sdlc_crew", roles)
    if not allowed_acl:
        duration_ms = round((time.perf_counter() - t_start) * 1000, 2)
        res = f"⛔ {acl_err}"
        tracer.record_mcp_tool_execution(
            tool_name="run_sdlc_crew",
            parameters={"issue_title": validated.issue_title, **attribution},
            result=res,
            roles=roles,
            duration_ms=duration_ms,
            error=acl_err,
        )
        return res

    allowed_rate, remaining_reqs, retry_after = mcp_rate_limiter.allow_request(caller_key)
    if not allowed_rate:
        duration_ms = round((time.perf_counter() - t_start) * 1000, 2)
        err = f"Rate limit exceeded for caller '{caller_key}'. Retry after {retry_after}s."
        res = f"⛔ {err}"
        tracer.record_mcp_tool_execution(
            tool_name="run_sdlc_crew",
            parameters={"issue_title": validated.issue_title, **attribution},
            result=res,
            roles=roles,
            duration_ms=duration_ms,
            error=err,
        )
        return res

    est_tokens = TokenCircuitBreaker.estimate_tokens(
        f"{validated.issue_title} {validated.issue_description}"
    )
    allowed_tokens, remaining_tokens, token_err = mcp_token_breaker.check_and_consume(
        caller_key, est_tokens
    )
    if not allowed_tokens:
        duration_ms = round((time.perf_counter() - t_start) * 1000, 2)
        res = f"⛔ {token_err}"
        tracer.record_mcp_tool_execution(
            tool_name="run_sdlc_crew",
            parameters={"issue_title": validated.issue_title, **attribution},
            result=res,
            roles=roles,
            duration_ms=duration_ms,
            error=token_err,
        )
        return res

    sandbox_root = Path(os.getenv("SDLC_SANDBOX_ROOT", os.getcwd())).resolve()
    recalled = HermesSkillSynthesizer.recall_relevant_skills(
        sandbox_root, f"{validated.issue_title} {validated.issue_description}"
    )
    crew_result = SDLCCrewOrchestrator.kickoff_crew(
        validated.issue_title, validated.issue_description
    )
    payload_out = json.dumps({
        "crew_execution": crew_result,
        "recalled_hermes_skills_count": len(recalled),
        "authorized_roles": roles,
    })
    duration_ms = round((time.perf_counter() - t_start) * 1000, 2)
    tracer.record_mcp_tool_execution(
        tool_name="run_sdlc_crew",
        parameters={
            "issue_title": validated.issue_title,
            "rate_limit_remaining": remaining_reqs,
            "token_budget_remaining": remaining_tokens,
            **attribution,
        },
        result=payload_out,
        roles=roles,
        duration_ms=duration_ms,
    )
    return payload_out


@mcp.tool()
async def recall_hermes_skills(
    query: str,
    max_skills: int = 2,
    auth_token: Optional[str] = None,
) -> str:
    """
    Recall portable Hermes Agent SKILL.md playbooks (`.agent/skills/hermes-*/SKILL.md`)
    matching `query` so external Hermes or MCP clients can reuse verified fixes.
    """
    from agent.workflow import HermesSkillSynthesizer

    t_start = time.perf_counter()
    validated = MCPHermesSkillRequest(
        query=query,
        max_skills=max_skills,
        auth_token=auth_token,
    )
    roles, error = _resolve_tool_roles(validated.auth_token)
    attribution = _resolve_caller_attribution(validated.auth_token)
    caller_key = attribution["caller_sub"]

    if error:
        duration_ms = round((time.perf_counter() - t_start) * 1000, 2)
        res = f"⛔ {error}"
        tracer.record_mcp_tool_execution(
            tool_name="recall_hermes_skills",
            parameters={"query": validated.query, **attribution},
            result=res,
            roles=roles,
            duration_ms=duration_ms,
            error=error,
        )
        return res

    allowed_acl, acl_err = check_tool_permission("recall_hermes_skills", roles)
    if not allowed_acl:
        duration_ms = round((time.perf_counter() - t_start) * 1000, 2)
        res = f"⛔ {acl_err}"
        tracer.record_mcp_tool_execution(
            tool_name="recall_hermes_skills",
            parameters={"query": validated.query, **attribution},
            result=res,
            roles=roles,
            duration_ms=duration_ms,
            error=acl_err,
        )
        return res

    allowed_rate, remaining_reqs, retry_after = mcp_rate_limiter.allow_request(caller_key)
    if not allowed_rate:
        duration_ms = round((time.perf_counter() - t_start) * 1000, 2)
        err = f"Rate limit exceeded for caller '{caller_key}'. Retry after {retry_after}s."
        res = f"⛔ {err}"
        tracer.record_mcp_tool_execution(
            tool_name="recall_hermes_skills",
            parameters={"query": validated.query, **attribution},
            result=res,
            roles=roles,
            duration_ms=duration_ms,
            error=err,
        )
        return res

    est_tokens = TokenCircuitBreaker.estimate_tokens(validated.query)
    allowed_tokens, remaining_tokens, token_err = mcp_token_breaker.check_and_consume(
        caller_key, est_tokens
    )
    if not allowed_tokens:
        duration_ms = round((time.perf_counter() - t_start) * 1000, 2)
        res = f"⛔ {token_err}"
        tracer.record_mcp_tool_execution(
            tool_name="recall_hermes_skills",
            parameters={"query": validated.query, **attribution},
            result=res,
            roles=roles,
            duration_ms=duration_ms,
            error=token_err,
        )
        return res

    sandbox_root = Path(os.getenv("SDLC_SANDBOX_ROOT", os.getcwd())).resolve()
    skills = HermesSkillSynthesizer.recall_relevant_skills(
        sandbox_root, validated.query, max_skills=validated.max_skills
    )
    payload_out = json.dumps({
        "query": validated.query,
        "matched_count": len(skills),
        "skills": skills,
    })
    duration_ms = round((time.perf_counter() - t_start) * 1000, 2)
    tracer.record_mcp_tool_execution(
        tool_name="recall_hermes_skills",
        parameters={
            "query": validated.query,
            "rate_limit_remaining": remaining_reqs,
            "token_budget_remaining": remaining_tokens,
            **attribution,
        },
        result=payload_out,
        roles=roles,
        duration_ms=duration_ms,
    )
    return payload_out


@mcp.tool()
async def list_documents(
    limit: int = 20,
    auth_token: Optional[str] = None,
    user_roles: Optional[List[str]] = None,
) -> str:
    """
    List documents pre-filtered by caller's verified roles using PostgreSQL GIN index.
    Fails closed if user has no authorized roles.
    """
    t_start = time.perf_counter()
    tool_req = MCPListDocumentsRequest(limit=limit, auth_token=auth_token, user_roles=user_roles)

    roles, auth_err = _resolve_tool_roles(tool_req.auth_token, tool_req.user_roles)
    if auth_err:
        tracer.record_mcp_tool_execution(
            tool_name="list_documents",
            parameters={"limit": tool_req.limit},
            result=auth_err,
            roles=roles,
            duration_ms=round((time.perf_counter() - t_start) * 1000, 2),
            error=auth_err,
        )
        return f"⛔ {auth_err}"

    allowed_perm, perm_err = check_tool_permission("list_documents", roles)
    if not allowed_perm:
        tracer.record_mcp_tool_execution(
            tool_name="list_documents",
            parameters={"limit": tool_req.limit},
            result=perm_err,
            roles=roles,
            duration_ms=round((time.perf_counter() - t_start) * 1000, 2),
            error=perm_err,
        )
        return f"⛔ {perm_err}"

    attribution = _resolve_caller_attribution(tool_req.auth_token)
    caller_key = attribution.get("caller_sub") or "anonymous"
    allowed_rate, _rem_reqs, retry_after = mcp_rate_limiter.allow_request(caller_key)
    if not allowed_rate:
        err_msg = f"Rate limit exceeded: caller '{caller_key}' hit threshold. Retry after {retry_after}s."
        tracer.record_mcp_tool_execution(
            tool_name="list_documents",
            parameters={"limit": tool_req.limit},
            result=err_msg,
            roles=roles,
            duration_ms=round((time.perf_counter() - t_start) * 1000, 2),
            error=err_msg,
        )
        return f"⛔ {err_msg}"

    try:
        docs = await DatabaseManager.list_documents(user_roles=roles, limit=tool_req.limit)
        payload = json.dumps({"count": len(docs), "documents": docs}, indent=2)
        tracer.record_mcp_tool_execution(
            tool_name="list_documents",
            parameters={"limit": tool_req.limit},
            result=f"{len(docs)} documents returned",
            roles=roles,
            duration_ms=round((time.perf_counter() - t_start) * 1000, 2),
        )
        return payload
    except Exception as exc:
        err_msg = f"Failed to list documents: {str(exc)}"
        tracer.record_mcp_tool_execution(
            tool_name="list_documents",
            parameters={"limit": tool_req.limit},
            result=err_msg,
            roles=roles,
            duration_ms=round((time.perf_counter() - t_start) * 1000, 2),
            error=err_msg,
        )
        return f"⛔ {err_msg}"


@mcp.tool()
async def get_gateway_metadata(
    auth_token: Optional[str] = None,
) -> str:
    """
    Expose RFC 9728 Protected Resource Metadata for dynamic MCP client discovery,
    including token verification authorities, tool-level ACL policies, rate limit quotas,
    and circuit breaker thresholds.
    """
    t_start = time.perf_counter()
    attribution = _resolve_caller_attribution(auth_token)
    metadata = {
        "resource": os.getenv("MCP_RESOURCE_INDICATOR", "https://enterprise-rag.internal/mcp"),
        "authorization_servers": [
            "https://accounts.google.com",
            f"https://securetoken.google.com/{os.getenv('PROJECT_ID', 'gen-lang-client-0795078481')}",
        ],
        "scopes_supported": ["openid", "email", "profile"],
        "bearer_methods_supported": ["header", "body"],
        "transports_supported": ["http", "streamable-http", "stdio", "sse"],
        "preferred_network_transport": "http",
        "rfc_compliance": ["RFC 9728", "RFC 8707", "OAuth 2.1"],
        "tool_catalog": [
            {
                "name": "search_sdlc_context",
                "risk_tier": "read_only",
                "required_roles": ["engineer", "compliance_auditor", "finance_executive", "admin", "executive"],
                "rate_limit": f"{mcp_rate_limiter.max_requests} req / {mcp_rate_limiter.window_seconds}s",
            },
            {
                "name": "propose_patch",
                "risk_tier": "mutation_high_risk",
                "required_roles": ["engineer", "admin"],
                "rate_limit": f"{mcp_rate_limiter.max_requests} req / {mcp_rate_limiter.window_seconds}s",
            },
            {
                "name": "run_sdlc_crew",
                "risk_tier": "orchestration_tiered",
                "required_roles": ["engineer", "admin"],
                "rate_limit": f"{mcp_rate_limiter.max_requests} req / {mcp_rate_limiter.window_seconds}s",
            },
            {
                "name": "recall_hermes_skills",
                "risk_tier": "read_only",
                "required_roles": ["engineer", "compliance_auditor", "finance_executive", "admin", "executive"],
                "rate_limit": f"{mcp_rate_limiter.max_requests} req / {mcp_rate_limiter.window_seconds}s",
            },
            {
                "name": "get_gateway_metadata",
                "risk_tier": "discovery",
                "required_roles": ["*"],
                "rate_limit": "unthrottled",
            },
        ],
        "rate_limiter": {
            "type": "SlidingWindowRateLimiter",
            "window_seconds": mcp_rate_limiter.window_seconds,
            "max_requests": mcp_rate_limiter.max_requests,
        },
        "circuit_breaker": {
            "type": "TokenCircuitBreaker",
            "max_tokens_per_request": mcp_token_breaker.max_tokens_per_request,
            "max_tokens_per_issue": mcp_token_breaker.max_tokens_per_issue,
        },
        "caller_attribution": attribution,
    }
    duration_ms = round((time.perf_counter() - t_start) * 1000, 2)
    tracer.record_mcp_tool_execution(
        tool_name="get_gateway_metadata",
        parameters=attribution,
        result="RFC 9728 Protected Resource Metadata returned",
        roles=None,
        duration_ms=duration_ms,
    )
    return json.dumps(metadata, indent=2)


@mcp.resource("policy://sdlc-budget")
def get_budget_policy() -> str:
    return json.dumps({
        "max_tokens_per_request": mcp_token_breaker.max_tokens_per_request,
        "max_tokens_per_issue": mcp_token_breaker.max_tokens_per_issue,
        "rate_limit_max_requests": mcp_rate_limiter.max_requests,
        "rate_limit_window_seconds": mcp_rate_limiter.window_seconds,
        "max_steps": 10,
        "allowed_tools": [
            "search_sdlc_context",
            "propose_patch",
            "run_sdlc_crew",
            "recall_hermes_skills",
            "get_gateway_metadata",
        ],
    })


def run_server(
    transport: Optional[str] = None,
    host: Optional[str] = None,
    port: Optional[int] = None,
) -> None:
    """
    Run the FastMCP gateway with configurable transport.
    Supports 'http' / 'streamable-http' (Streamable HTTP, the production network standard),
    'stdio' (local CLI/subprocesses), and 'sse' (legacy Server-Sent Events).

    Configuration priority:
    1. Explicit parameters passed to run_server()
    2. CLI arguments (--transport, --host, --port)
    3. Environment variables (MCP_TRANSPORT, MCP_HOST, MCP_PORT)
    4. Defaults: transport="stdio", host="127.0.0.1", port=8000
    """
    import argparse

    parser = argparse.ArgumentParser(description="SDLC-Harness FastMCP Gateway")
    parser.add_argument(
        "--transport",
        choices=["stdio", "sse", "http", "streamable-http"],
        default=os.getenv("MCP_TRANSPORT", "stdio"),
        help="Transport protocol (stdio, sse, http, streamable-http)",
    )
    parser.add_argument(
        "--host",
        default=os.getenv("MCP_HOST", "127.0.0.1"),
        help="Bind host for HTTP/SSE transports (default: 127.0.0.1)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.getenv("MCP_PORT", "8000")),
        help="Bind port for HTTP/SSE transports (default: 8000)",
    )
    args, _ = parser.parse_known_args()

    selected_transport = (transport or args.transport or "stdio").lower()
    selected_host = host or args.host or "127.0.0.1"
    selected_port = port or args.port or 8000

    if selected_transport in ("sse", "http", "streamable-http"):
        logger.info(
            "Starting FastMCP gateway on %s://%s:%s",
            selected_transport,
            selected_host,
            selected_port,
        )
        mcp.run(
            transport=selected_transport,
            host=selected_host,
            port=selected_port,
        )
    else:
        logger.info("Starting FastMCP gateway over stdio transport")
        mcp.run(transport="stdio")


if __name__ == "__main__":
    run_server()
