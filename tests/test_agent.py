"""
tests/test_agent.py
-------------------
Consolidated unit and lifecycle tests for the autonomous SDLC agent,
including guardrails, AST security, webhook parsing, and LangGraph workflow.
"""

import subprocess
import pytest

from agent import (
    PolicyEngine,
    parse_github_webhook,
    verify_github_signature,
    LangGraphSDLCWorkflow,
)


def git(root, *args):
    return subprocess.run(
        ["git", *args], cwd=root, check=True, capture_output=True, text=True
    )


# ---------------------------------------------------------------------------
# Guardrails & AST Policy Tests
# ---------------------------------------------------------------------------

def test_secret_scanning():
    content_with_secret = "api_key = 'sk-abcdef1234567890abcdef1234567890'"
    violations = PolicyEngine.scan_for_secrets(content_with_secret)
    assert len(violations) > 0
    assert "sk-" in violations[0]

    safe_content = "api_key = 'safe_value'"
    violations = PolicyEngine.scan_for_secrets(safe_content)
    assert len(violations) == 0


def test_ast_verification():
    dangerous_code = "eval('os.system(\"rm -rf /\")')"
    violations = PolicyEngine.verify_ast(dangerous_code)
    assert any("eval" in v for v in violations)

    dunder_import = "x = __import__('os')"
    violations = PolicyEngine.verify_ast(dunder_import)
    assert any("__import__" in v for v in violations)

    safe_code = "x = 1 + 1\nprint(x)"
    violations = PolicyEngine.verify_ast(safe_code)
    assert len(violations) == 0


@pytest.mark.asyncio
async def test_evaluate_patch():
    result = await PolicyEngine.evaluate_patch(
        file_path="src/main.py",
        content="def hello():\n    return 'world'",
        applied_adrs=["ADR-001"],
        test_trace="All tests passed",
    )
    assert result.passed is True
    assert "ADR-001" in result.audit_summary
    assert "✅ PASSED" in result.audit_summary


# ---------------------------------------------------------------------------
# Webhook Parser & Signature Tests
# ---------------------------------------------------------------------------

def test_webhook_parsing():
    payload = {
        "issue": {
            "number": 123,
            "title": "Fix bug in auth",
            "body": "The auth module is failing",
        },
        "repository": {"full_name": "org/repo"},
    }
    event = parse_github_webhook(payload)
    assert event.issue_id == "123"
    assert event.source == "github"
    assert event.title == "Fix bug in auth"


def test_webhook_signature():
    secret = "test-secret"
    body = b'{"hello": "world"}'
    import hmac, hashlib
    digest = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    valid_sig = f"sha256={digest}"

    assert verify_github_signature(body, valid_sig, secret) is True
    assert verify_github_signature(body, "sha256=invalid", secret) is False
    assert verify_github_signature(body, None, None) is True


# ---------------------------------------------------------------------------
# LangGraph Workflow Integration Test
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_langgraph_workflow_execution(tmp_path):
    git(tmp_path, "init")
    git(tmp_path, "config", "user.email", "test@example.com")
    git(tmp_path, "config", "user.name", "Test")
    (tmp_path / "value.py").write_text("VALUE = 1\n", encoding="utf-8")
    (tmp_path / "test_value.py").write_text(
        "from value import VALUE\n\ndef test_value():\n    assert VALUE == 2\n",
        encoding="utf-8",
    )
    git(tmp_path, "add", ".")
    git(tmp_path, "commit", "-m", "initial")

    payload = {
        "issue": {"number": 123, "title": "Fix value", "body": "Update the value."},
        "repository": {"full_name": "org/repo"},
        "patches": [{"file_path": "value.py", "content": "VALUE = 2\n"}],
    }

    workflow = LangGraphSDLCWorkflow(
        sandbox_root=str(tmp_path),
        test_command="python -m pytest -q",
        push=False,
    )
    result = await workflow.run(payload)

    assert result["status"] == "completed"
    assert "AGENT-123" in result["branch"]
    assert result["pushed"] is False
    assert "Fix value" in git(tmp_path, "log", "-1", "--format=%s").stdout
