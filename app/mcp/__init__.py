"""
app/mcp package
---------------
FastMCP gateway for Zero-Trust SDLC context retrieval, patch submission,
and operational budget policies.
"""

from app.mcp.gateway import (
    mcp,
    run_server,
    _resolve_tool_roles,
    search_sdlc_context,
    propose_patch,
    get_budget_policy,
)

__all__ = [
    "mcp",
    "run_server",
    "_resolve_tool_roles",
    "search_sdlc_context",
    "propose_patch",
    "get_budget_policy",
]

