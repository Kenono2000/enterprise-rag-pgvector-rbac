"""
incident_agent
--------------
Incident investigator agent — a self-study implementation of the KDnuggets
(Bala Priya C) 7-step agentic-system-design roadmap applied to this repository.

Public surface:
- :class:`incident_agent.loop.ReasonActLoop` — hand-built reason-act-observe loop
- :func:`incident_agent.loop.fixed_triage_pipeline` — Step 1 fixed workflow
- :class:`incident_agent.tools.IncidentToolRegistry` — six read-only tools
- :class:`incident_agent.memory.IncidentMemory` — SQLite solved-incident store
- :class:`incident_agent.orchestrator.IncidentOrchestrator` — orchestrator-workers
- :class:`incident_agent.eval.ReplayEvaluator` — 30-incident replay scoreboard
- :class:`incident_agent.guardrails.InvestigationGuardrails` — deployment bounds
- :class:`incident_agent.runner.IncidentInvestigator` — unified guarded facade
"""

from __future__ import annotations

from incident_agent.eval import ReplayEvaluator, build_replay_suite
from incident_agent.guardrails import (
    InvestigationGuardrails,
    RunBudgets,
    fence_tool_output,
)
from incident_agent.loop import ReasonActLoop, fixed_triage_pipeline
from incident_agent.memory import IncidentMemory, Scratchpad, compact_output
from incident_agent.models import (
    Incident,
    IncidentSeverity,
    InvestigationReport,
    RootCauseCandidate,
    ToolCallRecord,
)
from incident_agent.orchestrator import IncidentOrchestrator
from incident_agent.runner import (
    IncidentInvestigator,
    handle_alert_webhook,
    verify_webhook_signature,
)
from incident_agent.tools import IncidentToolRegistry, ToolResult

__all__ = [
    "ReasonActLoop",
    "fixed_triage_pipeline",
    "IncidentToolRegistry",
    "ToolResult",
    "IncidentMemory",
    "Scratchpad",
    "compact_output",
    "IncidentOrchestrator",
    "ReplayEvaluator",
    "build_replay_suite",
    "InvestigationGuardrails",
    "RunBudgets",
    "fence_tool_output",
    "IncidentInvestigator",
    "handle_alert_webhook",
    "verify_webhook_signature",
    "Incident",
    "IncidentSeverity",
    "InvestigationReport",
    "RootCauseCandidate",
    "ToolCallRecord",
]
