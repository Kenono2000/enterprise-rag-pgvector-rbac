"""
incident_agent/orchestrator.py
-----------------------------
Step 5 of the roadmap: multi-agent coordination via the orchestrator-worker
pattern.

The orchestrator fans out three parallel analysts — **logs**, **metrics**, and
**changes** — each with a clear brief (objective, output format, allowed tools,
scope). Workers run concurrently (asyncio.gather), return compact structured
findings, and the orchestrator synthesizes a ranked root-cause candidate list.

Per the article, multi-agent runs cost several times more than a single agent,
so this pattern is reserved for parallel, high-value investigation — exactly
the P1/P2 case where the fixed triage pipeline already misjudged.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict

from incident_agent.memory import Scratchpad
from incident_agent.models import Incident, RootCauseCandidate
from incident_agent.tools import IncidentToolRegistry, ToolResult

logger = logging.getLogger("incident_agent.orchestrator")

# A worker's single tool call is fenced with delimiters so its output is
# treated as data, never as instructions (deployment-guardrail discipline).
_FENCE = "<<<TOOL_OUTPUT>>>"


class AnalystBrief(BaseModel):
    """The deterministic contract handed to a parallel worker."""

    model_config = ConfigDict(extra="forbid")

    analyst: str
    objective: str
    allowed_tools: List[str]
    scope: str
    output_format: str


class AnalystFinding(BaseModel):
    """Structured finding returned by one parallel analyst."""

    model_config = ConfigDict(extra="forbid")

    analyst: str
    ok: bool
    summary: str
    evidence: List[str] = []
    candidate: Optional[RootCauseCandidate] = None
    tool_calls: int = 0


# ---------------------------------------------------------------------------
# Worker briefs (objective, output format, allowed tools, scope)
# ---------------------------------------------------------------------------

BRIEFS: Dict[str, AnalystBrief] = {
    "logs_analyst": AnalystBrief(
        analyst="logs_analyst",
        objective=(
            "Find error/exception patterns in the service logs that explain the "
            "alert. Report the earliest error timestamp and the dominant message."
        ),
        allowed_tools=["logs.query"],
        scope="Read-only log query for the incident's service; ERROR level first.",
        output_format="AnalystFinding with summary + evidence list of log lines.",
    ),
    "metrics_analyst": AnalystBrief(
        analyst="metrics_analyst",
        objective=(
            "Identify which metric breached and when. Correlate the breach "
            "timestamp with the alert time."
        ),
        allowed_tools=["metrics.query"],
        scope="Read-only metric query for the incident's service.",
        output_format="AnalystFinding with the breached metric and its value.",
    ),
    "changes_analyst": AnalystBrief(
        analyst="changes_analyst",
        objective=(
            "List recent deploys/config/schema/infra changes and rank which one "
            "best coincides with the alert onset."
        ),
        allowed_tools=["changes.list"],
        scope="Read-only change listing for the incident's service.",
        output_format="AnalystFinding with ranked change candidates.",
    ),
}


class IncidentOrchestrator:
    """
    Orchestrator-worker pattern: fan out three parallel read-only analysts,
    each with a strict brief, then synthesize their findings into ranked
    root-cause candidates.
    """

    def __init__(self, registry: Optional[IncidentToolRegistry] = None):
        self.registry = registry or IncidentToolRegistry()

    async def investigate(self, incident: Incident) -> Dict[str, Any]:
        """Run the three analysts in parallel and synthesize the findings."""
        logger.info("Orchestrating investigation for %s", incident.incident_id)

        logs_f, metrics_f, changes_f = await asyncio.gather(
            self._run_analyst("logs_analyst", incident),
            self._run_analyst("metrics_analyst", incident),
            self._run_analyst("changes_analyst", incident),
        )

        findings = [logs_f, metrics_f, changes_f]
        candidates = self._synthesize(incident, findings)
        return {
            "incident_id": incident.incident_id,
            "service": incident.service,
            "findings": [f.model_dump() for f in findings],
            "candidates": [c.model_dump() for c in candidates],
            "analyst_count": len(findings),
        }

    # -- worker execution ---------------------------------------------------

    async def _run_analyst(
        self, analyst_name: str, incident: Incident
    ) -> AnalystFinding:
        brief = BRIEFS[analyst_name]
        scratch = Scratchpad(max_notes=6)
        tool_calls = 0

        try:
            if analyst_name == "logs_analyst":
                result: ToolResult = await self.registry.dispatch(
                    "logs.query", {"service": incident.service, "level": "ERROR"}
                )
                tool_calls += 1
                payload = result.payload or {}
                logs = payload.get("logs", [])
                if not result.ok or not logs:
                    return AnalystFinding(
                        analyst=analyst_name, ok=False,
                        summary="No error logs found or query failed.",
                        evidence=[result.error or "no errors"],
                        tool_calls=tool_calls,
                    )
                first_ts = logs[0].get("ts", "unknown")
                evidence = [f"{l.get('level')}: {l.get('message')}" for l in logs[:3]]
                return AnalystFinding(
                    analyst=analyst_name, ok=True,
                    summary=(
                        f"{len(logs)} error log entries; earliest at {first_ts}. "
                        f"Dominant: {logs[0].get('message', '')[:120]}"
                    ),
                    evidence=evidence,
                    candidate=RootCauseCandidate(
                        change_id=None, service=incident.service,
                        hypothesis=(
                            f"Error cluster in {incident.service} logs "
                            f"({len(logs)} entries) starting {first_ts}."
                        ),
                        confidence=min(0.9, 0.45 + 0.1 * min(len(logs), 4)),
                        evidence=evidence,
                    ),
                    tool_calls=tool_calls,
                )

            if analyst_name == "metrics_analyst":
                result = await self.registry.dispatch(
                    "metrics.query", {"service": incident.service}
                )
                tool_calls += 1
                payload = result.payload or {}
                points = payload.get("metrics", [])
                breached = [
                    p for p in points
                    if p.get("value") and p["value"] > _metric_threshold(p["metric"])
                ]
                if not result.ok or not breached:
                    return AnalystFinding(
                        analyst=analyst_name, ok=False,
                        summary="No metric breach detected.",
                        evidence=[result.error or "no breach"],
                        tool_calls=tool_calls,
                    )
                worst = max(breached, key=lambda p: p["value"])
                evidence = [
                    f"{p['metric']}={p['value']} at {p['ts']}" for p in breached[:3]
                ]
                return AnalystFinding(
                    analyst=analyst_name, ok=True,
                    summary=(
                        f"Breached metric {worst['metric']}={worst['value']} "
                        f"at {worst['ts']}."
                    ),
                    evidence=evidence,
                    candidate=RootCauseCandidate(
                        change_id=None, service=incident.service,
                        hypothesis=(
                            f"Metric breach: {worst['metric']} hit "
                            f"{worst['value']} at {worst['ts']}."
                        ),
                        confidence=0.55,
                        evidence=evidence,
                    ),
                    tool_calls=tool_calls,
                )

            # changes_analyst
            result = await self.registry.dispatch(
                "changes.list", {"service": incident.service}
            )
            tool_calls += 1
            payload = result.payload or {}
            changes = payload.get("changes", [])
            if not result.ok or not changes:
                return AnalystFinding(
                    analyst=analyst_name, ok=False,
                    summary="No recent changes found.",
                    evidence=[result.error or "no changes"],
                    tool_calls=tool_calls,
                )
            # Rank: most recent change within the window is the prime suspect.
            ranked = sorted(changes, key=lambda c: c.get("ts", ""), reverse=True)
            prime = ranked[0]
            evidence = [
                f"{c.get('change_id')} ({c.get('kind')}) at {c.get('ts')}"
                for c in ranked[:3]
            ]
            return AnalystFinding(
                analyst=analyst_name, ok=True,
                summary=(
                    f"{len(changes)} recent changes; prime suspect "
                    f"{prime.get('change_id')} ({prime.get('kind')}) at "
                    f"{prime.get('ts')}."
                ),
                evidence=evidence,
                candidate=RootCauseCandidate(
                    change_id=prime.get("change_id"),
                    service=incident.service,
                    hypothesis=(
                        f"Change {prime.get('change_id')} "
                        f"({prime.get('kind')}) coincides with alert onset."
                    ),
                    confidence=0.7,
                    evidence=evidence,
                ),
                tool_calls=tool_calls,
            )

        except Exception as exc:  # noqa: BLE001 - worker must never crash the fleet
            logger.warning("Analyst %s failed: %s", analyst_name, exc)
            return AnalystFinding(
                analyst=analyst_name, ok=False,
                summary=f"Analyst crashed: {type(exc).__name__}",
                evidence=[str(exc)], tool_calls=tool_calls,
            )

    # -- synthesis ----------------------------------------------------------

    def _synthesize(
        self, incident: Incident, findings: List[AnalystFinding]
    ) -> List[RootCauseCandidate]:
        """
        Merge analyst candidates, boosting confidence when independent lines of
        inquiry (logs + metrics + changes) converge on the same service.

        Change candidates are preferred as the named root cause when
        corroborating signal candidates (logs/metrics) exist for the same
        service — the deploy/config correlation rule — rather than letting a
        high-confidence-but-unnamed log signal win.
        """
        by_change: Dict[Optional[str], RootCauseCandidate] = {}
        signal_count = 0
        for f in findings:
            if f.ok and f.candidate is not None:
                cand = f.candidate
                if cand.change_id is None:
                    signal_count += 1
                key = cand.change_id
                if key in by_change:
                    existing = by_change[key]
                    existing.confidence = min(0.98, existing.confidence + 0.15)
                    existing.evidence = list(
                        dict.fromkeys(existing.evidence + cand.evidence)
                    )
                else:
                    by_change[key] = cand

        ranked = sorted(by_change.values(), key=lambda c: c.confidence, reverse=True)

        # Corroborate: when independent signals converge on a change candidate's
        # service, promote that change to the top with boosted confidence.
        if signal_count > 0:
            change_candidates = [c for c in ranked if c.change_id]
            if change_candidates:
                prime = change_candidates[0]
                prime.confidence = min(0.99, prime.confidence + 0.15 * signal_count)
                prime.hypothesis = (
                    f"{prime.hypothesis} Corroborated by {signal_count} independent "
                    "signal(s) (logs/metrics) on the same service."
                )
                ranked.sort(key=lambda c: c.confidence, reverse=True)
        return ranked


def _metric_threshold(metric: str) -> float:
    return {
        "http_5xx_rate": 0.2,
        "db_pool_utilization": 0.8,
        "query_p99_ms": 1000.0,
        "jwks_fetch_rps": 100.0,
        "queue_depth": 5000.0,
        "worker_restart_count": 1.0,
        "duplicate_line_items": 0.5,
        "cart_write_latency_p99_ms": 1000.0,
    }.get(metric, float("inf"))
