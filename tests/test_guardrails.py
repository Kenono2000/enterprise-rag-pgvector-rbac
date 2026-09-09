import pytest
import ast
from sdlc_harness.policies.guardrails import PolicyEngine

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
        test_trace="All tests passed"
    )
    assert result.passed is True
    assert "ADR-001" in result.audit_summary
    assert "✅ PASSED" in result.audit_summary
