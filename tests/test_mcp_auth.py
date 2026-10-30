"""
tests/test_mcp_auth.py
----------------------
Unit tests for Google OAuth token verification, RBAC resolution,
strict extra='forbid' schemas, sliding-window rate limiting, and
token circuit breakers in the FastMCP gateway (app/mcp/gateway.py).
"""

from unittest.mock import patch
import pytest
from pydantic import ValidationError

from app.mcp.gateway import (
    _resolve_tool_roles,
    check_tool_permission,
    get_gateway_metadata,
    search_sdlc_context,
    propose_patch,
    run_sdlc_crew,
    recall_hermes_skills,
    MCPSearchRequest,
    MCPPatchRequest,
    MCPSDLCCrewRequest,
    MCPHermesSkillRequest,
    mcp_rate_limiter,
    mcp_token_breaker,
)


@pytest.fixture(autouse=True)
def _reset_mcp_guardrails():
    mcp_rate_limiter.reset()
    mcp_token_breaker.reset()
    yield
    mcp_rate_limiter.reset()
    mcp_token_breaker.reset()


class TestMcpRoleResolution:
    def test_require_google_auth_without_token_fails(self, monkeypatch):
        monkeypatch.setenv("REQUIRE_GOOGLE_AUTH", "true")
        roles, err = _resolve_tool_roles(auth_token=None)
        assert roles is None
        assert "Authorization required" in err

    def test_dev_fallback_honored_when_require_google_false(self, monkeypatch):
        monkeypatch.setenv("REQUIRE_GOOGLE_AUTH", "false")
        roles, err = _resolve_tool_roles(auth_token=None, user_roles=["engineer"])
        assert err is None
        assert roles == ["engineer"]

    def test_invalid_token_returns_error(self, monkeypatch):
        monkeypatch.setenv("REQUIRE_GOOGLE_AUTH", "true")
        roles, err = _resolve_tool_roles(auth_token="invalid.jwt.token")
        assert roles is None
        assert "Token verification failed" in err

    @patch("app.mcp.gateway.verify_google_token")
    @patch("app.mcp.gateway.extract_roles")
    def test_valid_token_extracts_roles(self, mock_extract, mock_verify, monkeypatch):
        monkeypatch.setenv("REQUIRE_GOOGLE_AUTH", "true")
        mock_verify.return_value = {"sub": "user_123", "email": "alice@acme.com"}
        mock_extract.return_value = ["engineer", "compliance_auditor"]

        roles, err = _resolve_tool_roles(auth_token="valid.mock.token")
        assert err is None
        assert roles == ["engineer", "compliance_auditor"]


@pytest.mark.asyncio
class TestMcpToolsAuth:
    async def test_search_sdlc_context_blocked_without_auth(self, monkeypatch):
        monkeypatch.setenv("REQUIRE_GOOGLE_AUTH", "true")
        result = await search_sdlc_context(question="What are the guidelines?")
        assert "⛔ Authorization required" in result

    async def test_propose_patch_blocked_without_auth(self, monkeypatch):
        monkeypatch.setenv("REQUIRE_GOOGLE_AUTH", "true")
        result = await propose_patch(branch_name="feature/test", patch_content="diff")
        assert "⛔ Authorization required" in result

    @patch("app.mcp.gateway.verify_google_token")
    async def test_propose_patch_succeeds_with_auth(self, mock_verify, monkeypatch):
        monkeypatch.setenv("REQUIRE_GOOGLE_AUTH", "true")
        mock_verify.return_value = {"email": "dev@acme.com"}

        result = await propose_patch(
            branch_name="feature/test",
            patch_content="print('hello')",
            auth_token="valid.token",
        )
        assert "dev@acme.com" in result

    @patch("app.mcp.gateway.verify_google_token")
    async def test_run_sdlc_crew_and_recall_hermes_skills(self, mock_verify, monkeypatch):
        monkeypatch.setenv("REQUIRE_GOOGLE_AUTH", "true")
        blocked_crew = await run_sdlc_crew(issue_title="Test Crew")
        assert "⛔ Authorization required" in blocked_crew
        blocked_hermes = await recall_hermes_skills(query="PKCE auth")
        assert "⛔ Authorization required" in blocked_hermes

        mock_verify.return_value = {"email": "architect@acme.com", "sub": "arch-1"}
        crew_out = await run_sdlc_crew(
            issue_title="Harden RBAC filter",
            issue_description="Ensure SQL parameter binding",
            auth_token="valid.token",
        )
        assert "Principal SDLC Architect" in crew_out
        assert "Lead Security & AST Auditor" in crew_out

        hermes_out = await recall_hermes_skills(
            query="RBAC filter",
            auth_token="valid.token",
        )
        assert "matched_count" in hermes_out

    async def test_tool_permission_acl_blocks_unauthorized_roles(self):
        """Verify check_tool_permission enforces tool-level ACL and prevents confused deputy calls."""
        import asyncio
        await asyncio.sleep(0)
        # propose_patch requires engineer or admin
        ok_eng, err_eng = check_tool_permission("propose_patch", ["engineer"])
        assert ok_eng is True
        assert err_eng is None

        ok_fin, err_fin = check_tool_permission("propose_patch", ["finance_executive"])
        assert ok_fin is False
        assert "Tool authorization error" in err_fin

        # search_sdlc_context allows finance_executive
        ok_search, err_search = check_tool_permission("search_sdlc_context", ["finance_executive"])
        assert ok_search is True
        assert err_search is None

    async def test_get_gateway_metadata_rfc9728(self):
        """Verify get_gateway_metadata returns RFC 9728 & RFC 8707 compliant metadata."""
        import json
        meta_str = await get_gateway_metadata()
        meta = json.loads(meta_str)
        assert meta["resource"] == "https://enterprise-rag.internal/mcp"
        assert "https://accounts.google.com" in meta["authorization_servers"]
        assert "RFC 9728" in meta["rfc_compliance"]
        assert "RFC 8707" in meta["rfc_compliance"]
        tools = [t["name"] for t in meta["tool_catalog"]]
        assert "search_sdlc_context" in tools
        assert "propose_patch" in tools
        assert "get_gateway_metadata" in tools


class TestMcpStrictSchemasAndBlastRadius:
    def test_mcp_schemas_enforce_extra_forbid(self):
        with pytest.raises(ValidationError):
            MCPSearchRequest(
                question="What is the policy?",
                unexpected_field="hallucinated_param",
            )
        with pytest.raises(ValidationError):
            MCPPatchRequest(
                branch_name="feature/x",
                patch_content="diff",
                injected_flag=True,
            )
        with pytest.raises(ValidationError):
            MCPSDLCCrewRequest(
                issue_title="Test",
                rogue_param="blocked",
            )
        with pytest.raises(ValidationError):
            MCPHermesSkillRequest(
                query="RBAC",
                rogue_param="blocked",
            )

    @pytest.mark.asyncio
    @patch("app.mcp.gateway.verify_google_token")
    async def test_mcp_sliding_window_rate_limiter_trips(self, mock_verify, monkeypatch):
        monkeypatch.setenv("REQUIRE_GOOGLE_AUTH", "true")
        mock_verify.return_value = {"email": "rate-user@acme.com", "sub": "rate-user"}
        orig_max = mcp_rate_limiter.max_requests
        try:
            mcp_rate_limiter.max_requests = 2
            r1 = await propose_patch("feature/1", "print(1)", auth_token="tok")
            r2 = await propose_patch("feature/2", "print(2)", auth_token="tok")
            r3 = await propose_patch("feature/3", "print(3)", auth_token="tok")
            assert "Patch submitted" in r1
            assert "Patch submitted" in r2
            assert "⛔ Rate limit exceeded" in r3
        finally:
            mcp_rate_limiter.max_requests = orig_max

    @pytest.mark.asyncio
    @patch("app.mcp.gateway.verify_google_token")
    async def test_mcp_token_circuit_breaker_trips(self, mock_verify, monkeypatch):
        monkeypatch.setenv("REQUIRE_GOOGLE_AUTH", "true")
        mock_verify.return_value = {"email": "budget-user@acme.com", "sub": "budget-user"}
        orig_req_max = mcp_token_breaker.max_tokens_per_request
        try:
            mcp_token_breaker.max_tokens_per_request = 5
            result = await propose_patch(
                branch_name="feature/huge",
                patch_content="word " * 30,
                auth_token="tok",
            )
            assert "⛔ Token circuit breaker tripped" in result
        finally:
            mcp_token_breaker.max_tokens_per_request = orig_req_max


class TestMcpRunServer:
    @patch("app.mcp.gateway.mcp.run")
    def test_run_server_default_stdio(self, mock_run, monkeypatch):
        monkeypatch.delenv("MCP_TRANSPORT", raising=False)
        from app.mcp.gateway import run_server
        run_server(transport="stdio")
        mock_run.assert_called_once_with(transport="stdio")

    @patch("app.mcp.gateway.mcp.run")
    def test_run_server_sse_transport(self, mock_run):
        from app.mcp.gateway import run_server
        run_server(transport="sse", host="0.0.0.0", port=9000)
        mock_run.assert_called_once_with(
            transport="sse",
            host="0.0.0.0",
            port=9000,
        )

    @patch("app.mcp.gateway.mcp.run")
    def test_run_server_env_transport(self, mock_run, monkeypatch):
        monkeypatch.setenv("MCP_TRANSPORT", "streamable-http")
        monkeypatch.setenv("MCP_PORT", "8888")
        from app.mcp.gateway import run_server
        run_server()
        mock_run.assert_called_once_with(
            transport="streamable-http",
            host="127.0.0.1",
            port=8888,
        )


@pytest.mark.asyncio
async def test_mcp_observability_tracking(monkeypatch):
    """Verify MCP tool calls emit telemetry events to ObservabilityTracer."""
    from app.observability import tracer
    monkeypatch.setenv("REQUIRE_GOOGLE_AUTH", "true")

    # Blocked call
    await search_sdlc_context(question="What are the encryption standards?")
    
    summary = tracer.get_metrics_summary()
    assert summary["mcp_tool_executions"] >= 1

    recent = tracer.get_recent_metrics(limit=5)
    mcp_events = [m for m in recent if m.get("event") == "mcp_tool_execution"]
    assert len(mcp_events) >= 1
    assert mcp_events[-1]["tool_name"] == "search_sdlc_context"
    assert mcp_events[-1]["status"] == "error"
