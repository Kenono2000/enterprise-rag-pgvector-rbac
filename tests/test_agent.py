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
    PatchProposal,
    TestTriagerSubagent,
    CrossModelJudgeSubagent,
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
    assert result["subagent_routing"]["triager"] == "flash (test-triager)"
    assert result["subagent_routing"]["judge"] == "pro (cross-model-judge)"
    assert result["judge_verdict"]["verdict"] == "PASS"
    assert "Fix value" in git(tmp_path, "log", "-1", "--format=%s").stdout


def test_flash_test_triager_subagent():
    triager = TestTriagerSubagent()
    assert triager.model_tier == "flash"
    assert triager.name == "test-triager"

    passed_res = triager.classify_failure(0, "10 passed in 0.42s")
    assert passed_res.failure_category == "none"

    syntax_res = triager.classify_failure(
        1,
        "FAILED tests/test_auth.py::test_pkce - SyntaxError: invalid syntax",
    )
    assert syntax_res.failure_category == "compilation_error"
    assert "tests/test_auth.py::test_pkce" in syntax_res.failing_targets

    assert_res = triager.classify_failure(
        1,
        "FAILED tests/test_rag.py::test_rbac\nE   AssertionError: expected 200 got 403",
    )
    assert assert_res.failure_category == "assertion_failure"
    assert "tests/test_rag.py::test_rbac" in assert_res.failing_targets

    timeout_res = triager.classify_failure(
        1,
        "FAILED tests/test_db.py::test_pool - asyncio.TimeoutError: pool timed out",
    )
    assert timeout_res.failure_category == "timeout"


@pytest.mark.asyncio
async def test_pro_cross_model_judge_subagent():
    judge = CrossModelJudgeSubagent()
    assert judge.model_tier == "pro"
    assert judge.name == "cross-model-judge"

    safe_verdict = await judge.evaluate_diff(
        [PatchProposal(file_path="app/utils.py", content="def add(a: int, b: int) -> int:\n    return a + b\n")],
        requirements="Add integer helper",
    )
    assert safe_verdict.verdict == "PASS"
    assert safe_verdict.passed is True
    assert "app/utils.py:L1-L2" in safe_verdict.line_references

    unsafe_verdict = await judge.evaluate_diff(
        [PatchProposal(file_path="app/bad.py", content="x = 1\neval('os.system(\"id\")')\n")],
        requirements="Check security gate",
    )
    assert unsafe_verdict.verdict == "FAIL"
    assert unsafe_verdict.passed is False
    assert "app/bad.py:L2" in unsafe_verdict.line_references

