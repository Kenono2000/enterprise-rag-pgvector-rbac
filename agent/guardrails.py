"""
agent/guardrails.py
-------------------
Deterministic static policy checks, secret scanning, AST security inspection,
schema drift validation, sliding-window rate limiting, and token circuit breakers.
"""

from __future__ import annotations

import ast
import hashlib
import re
import time
from collections import deque
from typing import Deque, Dict, Iterable, List, Optional, Set, Tuple, Type
from pydantic import BaseModel, ConfigDict


class SecurityGateResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    passed: bool
    violations: List[str]
    audit_summary: str


class SlidingWindowRateLimiter:
    """
    Deterministic per-caller sliding-window rate limiter to contain burst traffic
    and blast radius across FastAPI and FastMCP tool surfaces.
    """

    def __init__(self, max_requests: int = 60, window_seconds: float = 60.0):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._windows: Dict[str, Deque[float]] = {}

    def allow_request(
        self,
        caller_id: str,
        now: Optional[float] = None,
    ) -> Tuple[bool, int, float]:
        """
        Evaluate whether `caller_id` is within the sliding-window quota.

        Returns:
            (allowed, remaining_requests, retry_after_seconds)
        """
        ts = now if now is not None else time.monotonic()
        key = (caller_id or "anonymous").strip() or "anonymous"
        bucket = self._windows.setdefault(key, deque())
        cutoff = ts - self.window_seconds

        while bucket and bucket[0] <= cutoff:
            bucket.popleft()

        if len(bucket) >= self.max_requests:
            retry_after = max(0.0, round(self.window_seconds - (ts - bucket[0]), 2))
            return False, 0, retry_after

        bucket.append(ts)
        remaining = max(0, self.max_requests - len(bucket))
        return True, remaining, 0.0

    def reset(self, caller_id: Optional[str] = None) -> None:
        if caller_id is None:
            self._windows.clear()
        else:
            self._windows.pop(caller_id, None)


class TokenCircuitBreaker:
    """
    Request-level and cumulative caller/issue token circuit breaker enforcing
    `policy://sdlc-budget` limits (`max_tokens_per_request`, `max_tokens_per_issue`),
    with managed limit enforcement toggles and emergency shutoff kill-switches.
    """

    def __init__(
        self,
        max_tokens_per_request: int = 8000,
        max_tokens_per_issue: int = 50000,
        enforce_limit: bool = True,
    ):
        self.max_tokens_per_request = max_tokens_per_request
        self.max_tokens_per_issue = max_tokens_per_issue
        self.enforce_limit = enforce_limit
        self._consumed: Dict[str, int] = {}
        self._enforce_overrides: Dict[str, bool] = {}
        self._blocked: Dict[str, bool] = {}

    @staticmethod
    def estimate_tokens(text: str) -> int:
        if not text:
            return 0
        # Deterministic ~4 chars/token heuristic bounded by word count
        return max(len(text.split()), (len(text) + 3) // 4)

    def set_enforce_limit(self, caller_key: Optional[str] = None, enforce: bool = True) -> None:
        """Toggle whether token consumption limits are strictly enforced or advisory."""
        if caller_key is None:
            self.enforce_limit = enforce
        else:
            self._enforce_overrides[(caller_key or "anonymous").strip() or "anonymous"] = enforce

    def is_enforce_limit(self, caller_key: Optional[str] = None) -> bool:
        if caller_key is None:
            return self.enforce_limit
        key = (caller_key or "anonymous").strip() or "anonymous"
        return self._enforce_overrides.get(key, self.enforce_limit)

    def set_blocked(self, caller_key: str, blocked: bool = True) -> None:
        """Emergency kill-switch to manually or automatically turn off token consumption."""
        key = (caller_key or "anonymous").strip() or "anonymous"
        self._blocked[key] = blocked

    def is_blocked(self, caller_key: str) -> bool:
        key = (caller_key or "anonymous").strip() or "anonymous"
        return self._blocked.get(key, False)

    def check_and_consume(
        self,
        caller_key: str,
        requested_tokens: int,
    ) -> Tuple[bool, int, Optional[str]]:
        """
        Validate request-level and cumulative token consumption before/after LLM execution.

        Returns:
            (allowed, remaining_budget, error_reason)
        """
        key = (caller_key or "anonymous").strip() or "anonymous"
        used = self._consumed.get(key, 0)
        should_enforce = self.is_enforce_limit(key)

        if self._blocked.get(key, False):
            return (
                False,
                max(0, self.max_tokens_per_issue - used),
                f"Token consumption turned off for caller '{key}': account is blocked or reached managed limit.",
            )

        if requested_tokens > self.max_tokens_per_request:
            return (
                False,
                max(0, self.max_tokens_per_issue - used),
                f"Token circuit breaker tripped: request tokens ({requested_tokens}) exceed max_tokens_per_request ({self.max_tokens_per_request}).",
            )

        if should_enforce and (used + requested_tokens > self.max_tokens_per_issue):
            self._blocked[key] = True
            return (
                False,
                max(0, self.max_tokens_per_issue - used),
                f"Token circuit breaker tripped: cumulative tokens ({used + requested_tokens}) exceed max_tokens_per_issue ({self.max_tokens_per_issue}).",
            )

        new_total = used + max(0, requested_tokens)
        self._consumed[key] = new_total
        return True, max(0, self.max_tokens_per_issue - new_total), None

    def get_usage(self, caller_key: str) -> int:
        return self._consumed.get((caller_key or "anonymous").strip() or "anonymous", 0)

    def reset(self, caller_key: Optional[str] = None) -> None:
        if caller_key is None:
            self._consumed.clear()
            self._blocked.clear()
            self._enforce_overrides.clear()
        else:
            key = (caller_key or "anonymous").strip() or "anonymous"
            self._consumed.pop(key, None)
            self._blocked.pop(key, None)
            self._enforce_overrides.pop(key, None)


class PolicyEngine:
    """Evaluates proposed code modifications for secrets, dangerous AST patterns, protected paths, and schema drift."""

    SECRET_PATTERNS = [
        re.compile(r"(?:sk-|key-|token-|secret-)[a-zA-Z0-9]{20,}", re.IGNORECASE),
        re.compile(r"-----BEGIN [A-Z ]+ PRIVATE KEY-----"),
        re.compile(r"AIza[0-9A-Za-z-_]{35}"),  # Google API Key
    ]

    PROTECTED_PATHS = (
        ".env",
        ".git/",
        "agent/guardrails.py",
        ".github/workflows/",
    )

    HIGH_RISK_PREFIXES = (
        "schema.sql",
        "app/auth/",
        "app/db/",
        "Dockerfile",
        "docker-compose.yml",
    )

    FORBIDDEN_ATTR_CALLS = {
        ("os", "system"),
        ("os", "popen"),
        ("pickle", "loads"),
        ("pickle", "load"),
        ("marshal", "loads"),
        ("marshal", "load"),
    }

    SUBPROCESS_FUNCS = {"run", "Popen", "call", "check_call", "check_output"}

    @classmethod
    def scan_for_secrets(cls, content: str) -> List[str]:
        violations = []
        for pattern in cls.SECRET_PATTERNS:
            if pattern.search(content):
                violations.append(f"Potential secret detected: {pattern.pattern}")
        return violations

    @classmethod
    def verify_protected_path(cls, file_path: str) -> List[str]:
        norm = re.sub(r"^(?:\./)+", "", (file_path or "").replace("\\", "/"))
        violations: List[str] = []
        for protected in cls.PROTECTED_PATHS:
            if norm == protected.rstrip("/") or norm.startswith(protected):
                violations.append(f"Protected path modification blocked: '{file_path}'")
        return violations

    @classmethod
    def classify_autonomy_risk(cls, file_paths: Iterable[str]) -> Tuple[str, List[str]]:
        """
        OpenCrew-style Autonomy Ladder: classify patch targets into 'low_risk' (autonomous)
        or 'high_risk' (requires human-in-the-loop sign-off for auth, DB, or container infra).
        """
        high_risk_files: List[str] = []
        for path in file_paths:
            norm = re.sub(r"^(?:\./)+", "", (path or "").replace("\\", "/"))
            if any(norm == prefix.rstrip("/") or norm.startswith(prefix) for prefix in cls.HIGH_RISK_PREFIXES):
                high_risk_files.append(path)
        tier = "high_risk" if high_risk_files else "low_risk"
        return tier, high_risk_files

    @classmethod
    def verify_ast(cls, content: str) -> List[str]:
        violations = []
        try:
            tree = ast.parse(content)
            for node in ast.walk(tree):
                if isinstance(node, ast.Call):
                    if isinstance(node.func, ast.Name):
                        if node.func.id in ("exec", "eval", "__import__", "compile"):
                            violations.append(f"Forbidden dynamic execution: {node.func.id}()")
                    elif isinstance(node.func, ast.Attribute):
                        if node.func.attr == "__import__":
                            violations.append("Forbidden dunder import: __import__()")
                        elif isinstance(node.func.value, ast.Name):
                            pair = (node.func.value.id, node.func.attr)
                            if pair in cls.FORBIDDEN_ATTR_CALLS:
                                violations.append(f"Forbidden unsafe call: {pair[0]}.{pair[1]}()")
                            elif pair[0] == "subprocess" and pair[1] in cls.SUBPROCESS_FUNCS:
                                for kw in node.keywords:
                                    if (
                                        kw.arg == "shell"
                                        and isinstance(kw.value, ast.Constant)
                                        and kw.value.value is True
                                    ):
                                        violations.append(
                                            f"Forbidden shell=True execution: subprocess.{pair[1]}(shell=True)"
                                        )
        except SyntaxError as e:
            violations.append(f"Syntax error in code: {str(e)}")
        return violations

    @classmethod
    def verify_schema_drift(
        cls,
        model_cls: Type[BaseModel],
        expected_required_fields: Iterable[str],
    ) -> List[str]:
        """
        Verify a Pydantic schema enforces `extra='forbid'` (`additionalProperties: False`)
        and retains all expected required fields to prevent breaking tool/API drift.
        """
        violations: List[str] = []
        schema = model_cls.model_json_schema()

        if schema.get("additionalProperties") is not False:
            violations.append(
                f"Schema '{model_cls.__name__}' must enforce extra='forbid' (additionalProperties=False)."
            )

        actual_required: Set[str] = set(schema.get("required", []))
        expected_set: Set[str] = set(expected_required_fields)
        missing_req = expected_set - actual_required
        if missing_req:
            violations.append(
                f"Breaking schema drift in '{model_cls.__name__}': missing required fields {sorted(missing_req)}."
            )

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
        violations.extend(cls.verify_protected_path(file_path))
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
    - Deterministic prefix-cached prompt assembly for KV cache reuse
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
    def build_prefix_cached_prompt(
        cls,
        context_chunks_text: str,
        user_question: str,
    ) -> dict:
        """
        Assemble a deterministic prefix-first prompt structure (`[STATIC SYSTEM + RBAC CONTEXT]` -> `[DYNAMIC TURN]`)
        with a SHA-256 `prefix_hash` so OpenAI/Gemini KV prefix caches hit across multi-turn queries.
        """
        system_prefix = cls.build_system_prompt()
        static_prefix = f"{system_prefix}\n\nAUTHORIZED CONTEXT:\n{context_chunks_text}"
        prefix_hash = hashlib.sha256(static_prefix.encode("utf-8")).hexdigest()[:16]
        full_prompt = f"{static_prefix}\n\nUSER QUESTION: {user_question}\nANSWER:"
        return {
            "prompt": full_prompt,
            "prefix_hash": prefix_hash,
            "static_prefix_tokens": TokenCircuitBreaker.estimate_tokens(static_prefix),
        }

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
