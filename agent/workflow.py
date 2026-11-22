"""
agent/workflow.py
-----------------
GitHub webhook payload parsing and HMAC-SHA256 signature verification.
"""

from __future__ import annotations

import hmac
import hashlib
import json
import asyncio
from typing import Optional, Literal, List, Dict, Any
from pydantic import BaseModel


class SDLCEvent(BaseModel):
    source: str
    event_type: str
    issue_id: str
    title: str
    description: str
    repository: str


class TriageSummary(BaseModel):
    failure_category: Literal["none", "compilation_error", "assertion_failure", "timeout"]
    failing_targets: List[str]
    concise_summary: str


class JudgeVerdict(BaseModel):
    model_tier: Literal["flash", "pro"]
    subagent_name: str
    verdict: Literal["PASS", "FAIL"]
    passed: bool
    score: float
    line_references: List[str]
    findings: List[str]


class AgentState(Dict[str, Any]):
    """State dictionary for the SDLC workflow."""
    pass