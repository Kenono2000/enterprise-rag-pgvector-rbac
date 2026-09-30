"""
tests/test_mcp_auth.py
----------------------
Unit tests for Google OAuth token verification and RBAC resolution
in the FastMCP gateway (app/mcp/gateway.py).
"""

from unittest.mock import patch
import pytest

from app.mcp.gateway import _resolve_tool_roles, search_sdlc_context, propose_patch


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
