"""
incident_agent/models.py
------------------------
Strict domain models for the incident investigator agent.

Every model uses ``extra='forbid'`` (mirroring the repository's zero-trust
Pydantic convention pinned by ``tests/test_architectural_invariants.py``) so
malformed payloads fail fast at the boundary instead of silently propagating.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field


class IncidentSeverity(str, Enum):
    P1 = "P1"
    P2 = "P2"
    P3 = "P3"
    P4 = "P4"


class IncidentStatus(str, Enum):
    OPEN = "open"
    INVESTIGATING = "investigating"
    RESOLVED = "resolved"


class Incident(BaseModel):
    """A synthetic production alert to be investigated."""

    model_config = ConfigDict(extra="forbid")

    incident_id: str = Field(min_length=1)
    service: str = Field(min_length=1)
    title: str = Field(min_length=1)
    severity: IncidentSeverity
    status: IncidentStatus = IncidentStatus.OPEN
    alert_fired_at: datetime
    summary: str = Field(min_length=1)
    runbook_hint: Optional[str] = None


class LogEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    timestamp: datetime
    level: str
    service: str
    message: str


class MetricPoint(BaseModel):
    model_config = ConfigDict(extra="forbid")

    timestamp: datetime
    metric: str
    value: float
    labels: Dict[str, str] = Field(default_factory=dict)


class ChangeEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    change_id: str = Field(min_length=1)
    timestamp: datetime
    service: str
    actor: str
    kind: str  # deploy | config | schema | infra
    description: str


class ToolCallRecord(BaseModel):
    """One dispatched tool invocation captured in the agent trace."""

    model_config = ConfigDict(extra="forbid")

    step: int
    tool: str
    arguments: Dict[str, Any] = Field(default_factory=dict)
    ok: bool
    output_preview: str = ""
    duration_ms: float = 0.0
    error: Optional[str] = None


class RootCauseCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    change_id: Optional[str] = None
    service: str
    hypothesis: str = Field(min_length=1)
    confidence: float = Field(ge=0.0, le=1.0)
    evidence: List[str] = Field(default_factory=list)


class InvestigationReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    incident_id: str
    root_cause: Optional[RootCauseCandidate] = None
    candidates: List[RootCauseCandidate] = Field(default_factory=list)
    tool_calls: List[ToolCallRecord] = Field(default_factory=list)
    steps_used: int = 0
    status: str = "inconclusive"
    notes: List[str] = Field(default_factory=list)
