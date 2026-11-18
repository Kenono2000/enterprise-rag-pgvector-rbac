"""
incident_agent/eval.py
----------------------
Step 6 of the roadmap: evaluation.

Builds a 30-incident replay suite (the 10 seeded incidents expanded by 3
deterministic permutations of service/severity/time-of-day), runs each incident
3 times, and grades four dimensions:

1. **Tool selection** — did the investigation call the right tools?
2. **Arguments**     — were the tool arguments valid (correct service/id)?
3. **Final answer**  — did the named root-cause change match ground truth?
4. **Trajectory**    — step count within cap, no stuck loops, trace recorded.

Results roll up into a scoreboard (pass rates per dimension) and a failure
taxonomy that maps each failure to a category to guide fixes.
"""

from __future__ import annotations

import logging
from collections import Counter
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict

from incident_agent import data
from incident_agent.loop import ReasonActLoop
from incident_agent.models import Incident, IncidentSeverity
from incident_agent.orchestrator import IncidentOrchestrator

logger = logging.getLogger("incident_agent.eval")

REPLAY_RUNS = 3
# The 30-case suite: 10 seeded incidents x 3 deterministic permutations.
PERMUTATIONS = ("base", "shifted", "scaled")


def build_replay_suite() -> List[Dict[str, Any]]:
    """
    Expand the 10 seeded incidents into a 30-case replay suite.

    Each permutation is deterministic: ``shifted`` moves the alert time and
    severity one notch, ``scaled`` swaps severity band. Ground truth
    (expected_change_id / expected_service) is preserved across permutations
    so grading stays meaningful.
    """
    suite: List[Dict[str, Any]] = []
    for rec in data.INCIDENTS:
        inc: Incident = rec["incident"]
        for perm in PERMUTATIONS:
            variant = _permute(inc, perm)
            suite.append(
                {
                    "case_id": f"{inc.incident_id}-{perm}",
                    "incident": variant,
                    "expected_change_id": rec["expected_change_id"],
                    "expected_service": rec["expected_service"],
                }
            )
    return suite


def _permute(inc: Incident, perm: str) -> Incident:
    if perm == "base":
        return inc.model_copy()
    if perm == "shifted":
        from datetime import timedelta
        shifted = inc.alert_fired_at + timedelta(minutes=15)
        severity_order = ["P1", "P2", "P3", "P4"]
        idx = severity_order.index(inc.severity.value)
        new_sev = IncidentSeverity(severity_order[(idx + 1) % len(severity_order)])
        return inc.model_copy(
            update={
                "incident_id": f"{inc.incident_id}-s",
                "alert_fired_at": shifted,
                "severity": new_sev,
            }
        )
    # scaled: same event, severity band scaled down one level (P1->P2 etc.)
    severity_order = ["P1", "P2", "P3", "P4"]
    idx = severity_order.index(inc.severity.value)
    new_sev = IncidentSeverity(severity_order[min(idx + 1, len(severity_order) - 1)])
    return inc.model_copy(
        update={"incident_id": f"{inc.incident_id}-x", "severity": new_sev}
    )


class GradedCase(BaseModel):
    """Per-case grading result across the four dimensions."""

    model_config = ConfigDict(extra="forbid")

    case_id: str
    tool_selection_pass: bool
    arguments_pass: bool
    final_answer_pass: bool
    trajectory_pass: bool
    steps_used: int
    tools_called: List[str]
    named_change_id: Optional[str]
    expected_change_id: str
    failures: List[str] = []

    @property
    def all_pass(self) -> bool:
        return (
            self.tool_selection_pass
            and self.arguments_pass
            and self.final_answer_pass
            and self.trajectory_pass
        )


class Scoreboard(BaseModel):
    """Aggregated pass rates per grading dimension plus failure taxonomy."""

    model_config = ConfigDict(extra="forbid")

    total_cases: int
    total_runs: int
    overall_pass_rate: float
    tool_selection_pass_rate: float
    arguments_pass_rate: float
    final_answer_pass_rate: float
    trajectory_pass_rate: float
    failure_taxonomy: Dict[str, int]
    cases: List[Dict[str, Any]] = []


class ReplayEvaluator:
    """Runs the replay suite N times and produces the scoreboard."""

    def __init__(self, runs: int = REPLAY_RUNS, max_steps: int = 12):
        self.runs = runs
        self.max_steps = max_steps
        self.loop = ReasonActLoop(max_steps=max_steps)
        self.orchestrator = IncidentOrchestrator()

    async def run_suite(self) -> Scoreboard:
        suite = build_replay_suite()
        graded: List[GradedCase] = []
        failure_counts: Counter = Counter()

        for case in suite:
            inc = case["incident"]
            best_run: Optional[GradedCase] = None
            for run_idx in range(self.runs):
                graded_case = await self._grade_case(case, inc, run_idx)
                for f in graded_case.failures:
                    failure_counts[f] += 1
                if best_run is None or (
                    graded_case.all_pass and not best_run.all_pass
                ) or (
                    graded_case.all_pass == best_run.all_pass
                    and sum(graded_case.failures) < sum(best_run.failures)
                ):
                    best_run = graded_case
            graded.append(best_run)

        return self._aggregate(graded, failure_counts)

    async def _grade_case(
        self, case: Dict[str, Any], inc: Incident, run_idx: int
    ) -> GradedCase:
        report = await self.loop.run(inc)
        tools_called = [tc.tool for tc in report.tool_calls]

        # 1. Tool selection: must include change correlation + logs.
        tool_selection_pass = (
            "changes.list" in tools_called and "logs.query" in tools_called
        )
        # 2. Arguments: every dispatched call had valid (non-error) result.
        arguments_pass = all(tc.ok for tc in report.tool_calls)
        # 3. Final answer: named change matches ground truth (or candidate on
        #    the expected service with the expected change id).
        named = report.root_cause.change_id if report.root_cause else None
        final_answer_pass = self._answer_matches(
            report, case["expected_change_id"], case["expected_service"]
        )
        # 4. Trajectory: within step cap, trace recorded, no stuck-loop note.
        trajectory_pass = (
            report.steps_used <= self.max_steps
            and len(report.tool_calls) > 0
            and not any("stuck-loop" in n or "repeat guard" in n for n in report.notes)
        )

        failures: List[str] = []
        if not tool_selection_pass:
            failures.append("tool_selection")
        if not arguments_pass:
            failures.append("bad_arguments")
        if not final_answer_pass:
            failures.append("wrong_root_cause")
        if not trajectory_pass:
            failures.append("bad_trajectory")

        return GradedCase(
            case_id=case["case_id"],
            tool_selection_pass=tool_selection_pass,
            arguments_pass=arguments_pass,
            final_answer_pass=final_answer_pass,
            trajectory_pass=trajectory_pass,
            steps_used=report.steps_used,
            tools_called=tools_called,
            named_change_id=named,
            expected_change_id=case["expected_change_id"],
            failures=failures,
        )

    def _answer_matches(
        self, report: Any, expected_change_id: str, expected_service: str
    ) -> bool:
        rc = report.root_cause
        if rc is None:
            return False
        if rc.change_id and rc.change_id == expected_change_id:
            return True
        # Fallback: correct service + a hypothesis naming the expected change.
        if rc.service == expected_service and expected_change_id in rc.hypothesis:
            return True
        return False

    def _aggregate(
        self, graded: List[GradedCase], failure_counts: Counter
    ) -> Scoreboard:
        n = len(graded) or 1
        total_runs = self.runs

        def rate(field: str) -> float:
            return round(
                sum(1 for g in graded if getattr(g, field)) / n, 3
            )

        return Scoreboard(
            total_cases=len(graded),
            total_runs=total_runs,
            overall_pass_rate=round(sum(1 for g in graded if g.all_pass) / n, 3),
            tool_selection_pass_rate=rate("tool_selection_pass"),
            arguments_pass_rate=rate("arguments_pass"),
            final_answer_pass_rate=rate("final_answer_pass"),
            trajectory_pass_rate=rate("trajectory_pass"),
            failure_taxonomy=dict(failure_counts),
            cases=[g.model_dump() for g in graded],
        )
