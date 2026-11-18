"""
incident_agent/runner.py
------------------------
Step 7 project addition: webhook-triggered investigation runs that sit alongside
on-call engineers (shadow mode first, then assist mode).

The runner is the production entry point. It:
1. Verifies the webhook signature (HMAC) before trusting any payload.
2. Applies the deployment guardrails (budgets, read-only least privilege).
3. Chooses the simplest effective shape: fixed triage first; only when the
   pipeline misjudges does it escalate to the multi-agent orchestrator.
4. Records solved incidents into long-term memory for future recall.
5. Gates any remediation behind a human approval card.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
from typing import Any, Dict, Optional

from incident_agent.guardrails import (
    InvestigationGuardrails,
    RemediationRequest,
    RemediationDecision,
    fence_tool_output,
)
from incident_agent.loop import ReasonActLoop, fixed_triage_pipeline
from incident_agent.memory import IncidentMemory
from incident_agent.models import Incident
from incident_agent.orchestrator import IncidentOrchestrator

logger = logging.getLogger("incident_agent.runner")


def verify_webhook_signature(body: bytes, signature: Optional[str], secret: Optional[str]) -> bool:
    """Verify HMAC-SHA256 webhook signature (mirrors agent/parser.py convention)."""
    if not secret:
        return True
    if not signature or not signature.startswith("sha256="):
        return False
    digest = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(signature[7:], digest)


class IncidentInvestigator:
    """
    Unified facade: fixed triage -> (if misjudged) hand-built loop or
    orchestrator-worker fan-out, bounded by guardrails, with long-term memory.
    """

    def __init__(
        self,
        guardrails: Optional[InvestigationGuardrails] = None,
        memory: Optional[IncidentMemory] = None,
        use_orchestrator: bool = True,
    ):
        self.guardrails = guardrails or InvestigationGuardrails()
        self.memory = memory or IncidentMemory()
        self.use_orchestrator = use_orchestrator
        self.loop = ReasonActLoop()
        self.orchestrator = IncidentOrchestrator()

    async def investigate(self, incident: Incident) -> Dict[str, Any]:
        """Run a full guarded investigation and return a structured result."""
        self.guardrails.start_run()
        self.guardrails.record_trace("investigation.started", {
            "incident_id": incident.incident_id, "service": incident.service
        })

        # Least privilege: assert the deployed toolset is read-only.
        for tool in ("incident.get", "changes.list", "logs.query", "metrics.query"):
            self.guardrails.assert_read_only(tool)

        triage = fixed_triage_pipeline(incident)
        self.guardrails.record_trace("triage.completed", {
            "channel": triage.channel, "misjudged": triage.misjudged
        })

        # Simplest effective shape: fixed pipeline first. Only escalate to the
        # (costlier) multi-agent path when the pipeline misjudged.
        if triage.misjudged and self.use_orchestrator:
            mode = "orchestrator_workers"
            orch_result = await self.orchestrator.investigate(incident)
            report = await self.loop.run(incident)
            result = {
                "incident_id": incident.incident_id,
                "mode": mode,
                "triage_channel": triage.channel,
                "pipeline_misjudged": True,
                "orchestrator_findings": orch_result,
                "report": report.model_dump(),
            }
        else:
            mode = "fixed_pipeline" if not triage.misjudged else "single_agent_loop"
            report = await self.loop.run(incident)
            result = {
                "incident_id": incident.incident_id,
                "mode": mode,
                "triage_channel": triage.channel,
                "pipeline_misjudged": triage.misjudged,
                "report": report.model_dump(),
            }

        # Persist solved incident to long-term memory for future recall.
        rc = report.root_cause
        if rc is not None and rc.confidence >= 0.85:
            self.memory.record_solved(
                incident_id=incident.incident_id,
                service=incident.service,
                title=incident.title,
                root_cause_change_id=rc.change_id,
                root_cause_hypothesis=rc.hypothesis,
                resolution=f"Auto-investigated; root cause change {rc.change_id}.",
                solved_at=incident.alert_fired_at.isoformat(),
            )

        # Fence every tool-output preview with delimiters so downstream
        # consumers treat it strictly as data, never as instructions
        # (prompt-injection control, Step 7 guardrail).
        fenced_report = report.model_dump()
        for call in fenced_report.get("tool_calls", []):
            call["output_preview"] = fence_tool_output(
                call.get("output_preview", "")
            )
        result["report"] = fenced_report

        self.guardrails.record_trace("investigation.completed", {
            "mode": result["mode"],
            "status": report.status,
            "steps": report.steps_used,
        })
        result["trace"] = self.guardrails.trace()
        return result

    def propose_remediation(
        self,
        incident_id: str,
        action: str,
        change_id: Optional[str] = None,
        rationale: str = "",
        approver: Optional[str] = None,
    ) -> RemediationDecision:
        """Approval-gated remediation: never executed autonomously."""
        request = RemediationRequest(
            incident_id=incident_id, action=action, change_id=change_id, rationale=rationale
        )
        decision = self.guardrails.gate_remediation(request, approver=approver)
        self.guardrails.record_trace("remediation.gated", {
            "incident_id": incident_id,
            "action": action,
            "approved": decision.approved,
            "decided_by": decision.decided_by,
        })
        return decision


def handle_alert_webhook(
    body: bytes,
    signature: Optional[str],
    secret: Optional[str],
    payload: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Webhook entry point (shadow/assist mode): verify signature, parse the alert
    into an Incident, and dispatch an investigation. Returns a run descriptor
    the on-call engineer can inspect; remediation stays approval-gated.
    """
    if not verify_webhook_signature(body, signature, secret):
        return {"status": "rejected", "reason": "invalid webhook signature"}

    incident = Incident(
        incident_id=payload["incident_id"],
        service=payload["service"],
        title=payload["title"],
        severity=payload["severity"],
        alert_fired_at=payload["alert_fired_at"],
        summary=payload["summary"],
        runbook_hint=payload.get("runbook_hint"),
    )
    return {
        "status": "accepted",
        "incident_id": incident.incident_id,
        "shadow_mode": True,
        "note": (
            "Investigation runs alongside on-call engineers; no remediation is "
            "executed without approval-gated sign-off."
        ),
        "incident": incident.model_dump(),
    }
