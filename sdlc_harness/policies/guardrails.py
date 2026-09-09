import ast
import re
from typing import List, Optional
from pydantic import BaseModel

class SecurityGateResult(BaseModel):
    passed: bool
    violations: List[str]
    audit_summary: str

class PolicyEngine:
    # Pattern for potential secrets: common API keys, private keys, etc.
    SECRET_PATTERNS = [
        re.compile(r"(?:sk-|key-|token-|secret-)[a-zA-Z0-9]{20,}", re.IGNORECASE),
        re.compile(r"-----BEGIN [A-Z ]+ PRIVATE KEY-----"),
        re.compile(r"AIza[0-9A-Za-z-_]{35}") # Google API Key
    ]

    @classmethod
    def scan_for_secrets(cls, content: str) -> List[str]:
        violations = []
        for pattern in cls.SECRET_PATTERNS:
            if pattern.search(content):
                violations.append(f"Potential secret detected: {pattern.pattern}")
        return violations

    @classmethod
    def verify_ast(cls, content: str) -> List[str]:
        violations = []
        try:
            tree = ast.parse(content)
            for node in ast.walk(tree):
                                # Block dynamic execution sinks
                if isinstance(node, ast.Call):
                    if isinstance(node.func, ast.Name):
                        if node.func.id in ("exec", "eval", "__import__"):
                            violations.append(f"Forbidden dynamic execution: {node.func.id}()")
                    elif isinstance(node.func, ast.Attribute):
                        # Block dangerous attribute calls
                        if node.func.attr == "__import__":
                            violations.append("Forbidden dunder import: __import__()")

        except SyntaxError as e:
            violations.append(f"Syntax error in code: {str(e)}")
        return violations

    @classmethod
    async def evaluate_patch(
        cls, 
        file_path: str, 
        content: str, 
        applied_adrs: List[str], 
        test_trace: str
    ) -> SecurityGateResult:
        """
        Runs deterministic static policy checks before PR creation.
        """
        violations = []
        violations.extend(cls.scan_for_secrets(content))
        violations.extend(cls.verify_ast(content))

        passed = len(violations) == 0
        
        audit_summary = f"### 🛡️ Automated Security Audit Summary\n"
        audit_summary += f"- **Target File**: `{file_path}`\n"
        audit_summary += f"- **Applied ADRs**: {', '.join(applied_adrs) if applied_adrs else 'None'}\n"
        audit_summary += f"- **Test Trace**: {test_trace}\n"
        audit_summary += f"- **Status**: {'✅ PASSED' if passed else '❌ FAILED'}\n"
        
        if not passed:
            audit_summary += "\n#### ⚠️ Violations:\n"
            for v in violations:
                audit_summary += f"- {v}\n"

        return SecurityGateResult(
            passed=passed,
            violations=violations,
            audit_summary=audit_summary
        )
