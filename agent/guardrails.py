"""
agent/guardrails.py
-------------------
Deterministic static policy checks, secret scanning, and AST security inspection.
"""

from __future__ import annotations

import ast
import re
from typing import List
from pydantic import BaseModel


class SecurityGateResult(BaseModel):
    passed: bool
    violations: List[str]
    audit_summary: str


class PolicyEngine:
    """Evaluates proposed code modifications for secrets and dangerous AST patterns."""

    SECRET_PATTERNS = [
        re.compile(r"(?:sk-|key-|token-|secret-)[a-zA-Z0-9]{20,}", re.IGNORECASE),
        re.compile(r"-----BEGIN [A-Z ]+ PRIVATE KEY-----"),
        re.compile(r"AIza[0-9A-Za-z-_]{35}"),  # Google API Key
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
                if isinstance(node, ast.Call):
                    if isinstance(node.func, ast.Name):
                        if node.func.id in ("exec", "eval", "__import__"):
                            violations.append(f"Forbidden dynamic execution: {node.func.id}()")
                    elif isinstance(node.func, ast.Attribute):
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
        test_trace: str,
    ) -> SecurityGateResult:
        """Runs deterministic static policy checks before PR creation."""
        violations = []
        violations.extend(cls.scan_for_secrets(content))
        violations.extend(cls.verify_ast(content))

        passed = len(violations) == 0

        audit_summary = "### 🛡️ Automated Security Audit Summary\n"
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
            audit_summary=audit_summary,
        )


class GroundingGuardrail:
    """
    Validates LLM-generated responses against strict grounding guardrails:
    - Explicit source citation format: [Doc: <Title>, Chunk <Index>]
    - Mandatory admission of unknown information when context is absent
    """
    CITATION_PATTERN = re.compile(r"\[Doc:\s*([^,\]]+),\s*Chunk\s*(\d+)\]")
    UNKNOWN_ADMISSION_PHRASES = [
        "i do not have sufficient information in the authorized documents",
        "no authorized documentation found",
        "not mentioned in the provided context",
        "insufficient information",
    ]

    @classmethod
    def build_system_prompt(cls) -> str:
        return (
            "You are a Zero-Trust Enterprise Knowledge Assistant.\n"
            "Answer the user's question STRICTLY and SOLELY using the authorized context chunks provided below.\n\n"
            "STRICT GROUNDING RULES:\n"
            "1. Every factual statement or claim MUST cite its source document and chunk index in the exact format: [Doc: <Title>, Chunk <Index>].\n"
            "2. If the authorized context does NOT contain enough information to answer the question completely and factually, "
            "you MUST explicitly admit: 'I do not have sufficient information in the authorized documents to answer this question.'\n"
            "3. Do NOT extrapolate, speculate, or introduce external information not contained in the authorized context.\n"
        )

    @classmethod
    def validate_response(cls, answer: str, context_chunks: List[dict]) -> dict:
        """
        Validate whether the response satisfies anti-hallucination and grounding rules.
        """
        lower = answer.lower()
        admitted_unknown = any(phrase in lower for phrase in cls.UNKNOWN_ADMISSION_PHRASES)
        citations = cls.CITATION_PATTERN.findall(answer)
        violations = []

        if not admitted_unknown and not citations:
            violations.append("Response lacks mandatory source citations [Doc: <Title>, Chunk <Index>] and did not admit unknown information.")

        available_titles = {c.get("title", "").strip().lower() for c in context_chunks if c.get("title")}
        if available_titles:
            for doc_title, _chunk_idx in citations:
                if doc_title.strip().lower() not in available_titles:
                    violations.append(f"Cited document '{doc_title}' was not found in authorized context chunks.")

        return {
            "grounded": len(violations) == 0,
            "admitted_unknown": admitted_unknown,
            "citations_found": citations,
            "violations": violations,
        }

