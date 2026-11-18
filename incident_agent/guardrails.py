"""
incident_agent/guardrails.py
----------------------------
Step 7 of the roadmap: deployment guardrails.

Before any run reaches production traffic the agent is bounded by:

- **Step caps**        — hard ceiling on reason-act-observe iterations.
- **Time budget**      — wall-clock deadline per investigation.
- **Cost/token budget** — cumulative token ceiling (reuses the repository's
  TokenCircuitBreaker discipline).
- **Least-privilege tools** — the deployed toolset is read-only; remediation is
  a separate, approval-gated action, never a default tool.
- **Human approval gate** — any proposed remediation (rollback, flag flip) must
  pass an ApprovalCard gate before execution.
- **Tracing**          — every run emits a structured trace record.
- **Tool-output fencing** — all tool output is wrapped in delimiters so it is
  treated as data, never as instructions.
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field

from agent.guardrails import TokenCircuitBreaker

DEFAULT_STEP_CAP = 12
DEFAULT_TIME_BUDGET_SECONDS = 120.0
DEFAULT_TOKEN_BUDGET = 40000

# Read-only least-privilege toolset deployed to the investigator.
READ_ONLY_TOOLS = [
    "incident.get",
    "incident.list",
    "logs.query",
    "metrics.query",
    "changes.list",
    "memory.recall_similar",
]


class RunBudgets(BaseModel):
    """Per-run resource budgets (step cap, time, tokens)."""

    model_config = ConfigDict(extra="forbid")

    max_steps: int = Field(default=DEFAULT_STEP_CAP, ge=1, le=50)
    time_budget_seconds: float = Field(default=DEFAULT_TIME_BUDGET_SECONDS, gt=0)
    token_budget: int = Field(default=DEFAULT_TOKEN_BUDGET, ge=1)


class ApprovalCard(BaseModel):
    """Human-in-the-loop gate for any remediation action."""

    model_config = ConfigDict(extra="forbid")

    incident_id: str
    proposed_action: str  # rollback | flag_flip | scale
    target_change_id: Optional[str] = None
    risk_tier: str = "high_risk"
    requires_human_approval: bool = True
    status: str = "pending_human_approval"
    reason: str = ""


class RemediationRequest(BaseModel):
    """A proposed remediation that MUST pass the approval gate."""

    model_config = ConfigDict(extra="forbid")

    incident_id: str
    action: str  # rollback | flag_flip | scale
    change_id: Optional[str] = None
    rationale: str = ""


class RemediationDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    incident_id: str
    approved: bool
    decided_by: str
    reason: str


class InvestigationGuardrails:
    """
    Runtime guardrails applied to every investigation run: budgets, least
    privilege, approval gating, and tracing.
    """

    def __init__(
        self,
        budgets: Optional[RunBudgets] = None,
        token_breaker: Optional[TokenCircuitBreaker] = None,
        approved_callers: Optional[List[str]] = None,
    ):
        self.budgets = budgets or RunBudgets()
        self.token_breaker = token_breaker or TokenCircuitBreaker(
            max_tokens_per_request=8000, max_tokens_per_issue=DEFAULT_TOKEN_BUDGET
        )
        self.approved_callers = approved_callers or ["oncall-lead"]
        self._run_started_at: Optional[float] = None
        self._trace: List[Dict[str, Any]] = []

    # -- budgets ------------------------------------------------------------

    def start_run(self) -> None:
        self._run_started_at = time.monotonic()
        self._trace = []

    def time_remaining_seconds(self) -> float:
        if self._run_started_at is None:
            return self.budgets.time_budget_seconds
        elapsed = time.monotonic() - self._run_started_at
        return max(0.0, self.budgets.time_budget_seconds - elapsed)

    def time_budget_exceeded(self) -> bool:
        return self.time_remaining_seconds() <= 0

    def step_cap_exceeded(self, steps_used: int) -> bool:
        return steps_used >= self.budgets.max_steps

    def consume_tokens(self, caller_key: str, estimated_tokens: int) -> bool:
        allowed, _remaining, _reason = self.token_breaker.check_and_consume(
            caller_key, estimated_tokens
        )
        return allowed

    # -- least privilege ----------------------------------------------------

    def is_tool_allowed(self, tool_name: str) -> bool:
        """Deployed investigator toolset is read-only by default."""
        return tool_name in READ_ONLY_TOOLS

    def assert_read_only(self, tool_name: str) -> None:
        if not self.is_tool_allowed(tool_name):
            raise PermissionError(
                f"Tool '{tool_name}' is outside the read-only investigator "
                f"toolset ({READ_ONLY_TOOLS}). Remediation requires a separate "
                "approval-gated action."
            )

    # -- approval gate ------------------------------------------------------

    def gate_remediation(
        self, request: RemediationRequest, approver: Optional[str] = None
    ) -> RemediationDecision:
        """
        Human approval gate: remediation (rollback / flag flip / scale) is never
        executed autonomously. It requires an explicit approver from the
        approved-callers list.
        """
        if approver is None or approver not in self.approved_callers:
            return RemediationDecision(
                incident_id=request.incident_id,
                approved=False,
                decided_by=approver or "none",
                reason=(
                    f"Remediation '{request.action}' blocked: no approved human "
                    f"sign-off. Approved callers: {self.approved_callers}."
                ),
            )
        return RemediationDecision(
            incident_id=request.incident_id,
            approved=True,
            decided_by=approver,
            reason=f"Remediation '{request.action}' approved by {approver}.",
        )

    # -- tracing ------------------------------------------------------------

    def record_trace(self, event: str, detail: Dict[str, Any]) -> None:
        self._trace.append(
            {"ts": time.time(), "event": event, "detail": detail}
        )

    def trace(self) -> List[Dict[str, Any]]:
        return list(self._trace)


def fence_tool_output(output: str) -> str:
    """
    Fence tool output with delimiters so it is unambiguously treated as data
    and never parsed as instructions (prompt-injection control).
    """
    return f"<<<TOOL_OUTPUT>>>\n{output}\n<<<END_TOOL_OUTPUT>>>"
