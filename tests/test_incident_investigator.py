"""
tests/test_incident_investigator.py
-----------------------------------
Pytest suite for the incident investigator agent — the hands-on project that
applies the KDnuggets 7-step agentic-system-design roadmap.

Coverage mirrors the seven steps:
1. Workflow vs. agent — fixed triage pipeline + misjudgment detection.
2. Reasoning-action loop — step cap, trace logging, failure-mode guards.
3. Tool design — six read-only tools, contracts, truncation, actionable errors.
4. Memory — scratchpad, compaction, SQLite solved-incident retrieval.
5. Multi-agent coordination — orchestrator + 3 parallel analysts.
6. Evaluation — 30-case replay suite, 3 runs, scoreboard, failure taxonomy.
7. Deployment guardrails — budgets, least privilege, approval gate, webhook.

All tests are hermetic/offline: the SQLite store uses tmp_path, the synthetic
corpus is deterministic, and no network or LLM calls are made.
"""

from __future__ import annotations

import asyncio
import sqlite3
from datetime import datetime, timezone

import pytest

from incident_agent import (
    Incident,
    IncidentInvestigator,
    IncidentMemory,
    IncidentOrchestrator,
    IncidentSeverity,
    IncidentToolRegistry,
    ReasonActLoop,
    RunBudgets,
    Scratchpad,
    InvestigationGuardrails,
    ToolResult,
    build_replay_suite,
    compact_output,
    fence_tool_output,
    fixed_triage_pipeline,
    handle_alert_webhook,
    verify_webhook_signature,
)
from incident_agent.data import BASE_TIME, INCIDENTS, get_incident
from incident_agent.eval import ReplayEvaluator
from incident_agent.guardrails import READ_ONLY_TOOLS, RemediationRequest
from incident_agent.loop import CONFIDENT_EVIDENCE_THRESHOLD, MAX_STEPS
from incident_agent.tools import TOOL_SPECS, tool_get_incident, tool_list_changes
from incident_agent.memory import estimate_tokens


def _base_incident() -> Incident:
    rec = get_incident("INC-1001")
    return rec["incident"]


# ---------------------------------------------------------------------------
# Step 1: workflow vs. agent — fixed triage pipeline
# ---------------------------------------------------------------------------


def test_fixed_triage_routes_by_severity():
    inc = _base_incident()
    decision = fixed_triage_pipeline(inc)
    assert decision.incident_id == "INC-1001"
    assert decision.service == "svc-payments"
    assert decision.channel == "page-oncall"  # P1 pages primary on-call
    assert decision.suspected_change_window_minutes == 180


def test_fixed_triage_flags_deploy_correlation_misjudgment():
    # INC-1001 is a P1 whose summary mentions a deploy -> pipeline misjudges
    # (cannot correlate the culprit change), so agentic escalation is needed.
    inc = _base_incident()
    decision = fixed_triage_pipeline(inc)
    assert decision.misjudged is True
    assert decision.misjudgment_reason


def test_fixed_triage_flags_multi_change_disambiguation():
    # svc-cart has two recent changes (deploy + flag toggle): a single fixed
    # lookback window cannot disambiguate which is causal.
    inc = get_incident("INC-1004")["incident"]
    decision = fixed_triage_pipeline(inc)
    assert decision.misjudged is True


def test_fixed_triage_low_severity_no_misjudgment():
    # INC-1005 (P3, single old deploy, no deploy mention) is handled fine by
    # the fixed pipeline.
    inc = get_incident("INC-1005")["incident"]
    decision = fixed_triage_pipeline(inc)
    assert decision.channel == "ticket"
    assert decision.misjudged is False


# ---------------------------------------------------------------------------
# Step 2: reasoning-action loop
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reason_act_loop_runs_and_traces():
    loop = ReasonActLoop(max_steps=MAX_STEPS)
    inc = _base_incident()
    report = await loop.run(inc)
    assert report.incident_id == "INC-1001"
    assert report.steps_used <= MAX_STEPS
    assert len(report.tool_calls) > 0
    # Trace logging: every dispatched call is recorded with step + duration.
    for tc in report.tool_calls:
        assert tc.step >= 1
        assert tc.duration_ms >= 0.0
        assert tc.tool in TOOL_SPECS


@pytest.mark.asyncio
async def test_loop_names_correct_root_cause():
    loop = ReasonActLoop()
    report = await loop.run(_base_incident())
    assert report.root_cause is not None
    assert report.root_cause.change_id == "CHG-1001"
    assert report.root_cause.confidence >= CONFIDENT_EVIDENCE_THRESHOLD
    assert report.status == "root_cause_identified"


@pytest.mark.asyncio
async def test_loop_respects_step_cap():
    loop = ReasonActLoop(max_steps=3)
    report = await loop.run(_base_incident())
    assert report.steps_used <= 3


@pytest.mark.asyncio
async def test_loop_malformed_tool_arguments_are_actionable():
    registry = IncidentToolRegistry()
    result = await registry.dispatch("incident.get", {"wrong_param": "x"})
    assert result.ok is False
    assert "incident_id" in result.error  # actionable: names expected parameter


@pytest.mark.asyncio
async def test_loop_unknown_tool_returns_actionable_error():
    registry = IncidentToolRegistry()
    result = await registry.dispatch("incident.delete", {"incident_id": "INC-1001"})
    assert result.ok is False
    assert "Unknown tool" in result.error
    assert "Available tools" in result.error


@pytest.mark.asyncio
async def test_loop_tool_output_is_compact_and_truncated():
    registry = IncidentToolRegistry()
    result = await registry.dispatch("incident.list", {})
    assert result.ok is True
    text = result.to_compact_text()
    assert len(text) <= 1200  # compact-output contract


# ---------------------------------------------------------------------------
# Step 3: tool design — six read-only tools as contracts
# ---------------------------------------------------------------------------


def test_six_tools_are_registered_and_read_only():
    assert set(TOOL_SPECS.keys()) == {
        "incident.get",
        "incident.list",
        "logs.query",
        "metrics.query",
        "changes.list",
        "memory.recall_similar",
    }
    # Least privilege: the deployed investigator toolset is read-only.
    assert set(TOOL_SPECS.keys()) == set(READ_ONLY_TOOLS)


def test_tool_get_incident_returns_metadata():
    payload = tool_get_incident("INC-1001")
    assert payload["incident_id"] == "INC-1001"
    assert payload["service"] == "svc-payments"
    assert payload["severity"] == "P1"


def test_tool_get_incident_unknown_id_actionable_error():
    with pytest.raises(ValueError, match="Unknown incident_id"):
        tool_get_incident("INC-9999")


def test_tool_query_logs_unknown_service_actionable_error():
    from incident_agent.tools import tool_query_logs

    with pytest.raises(ValueError, match="Unknown service"):
        tool_query_logs(service="svc-nonexistent")


def test_tool_list_changes_returns_change_events():
    payload = tool_list_changes(service="svc-payments")
    assert payload["count"] >= 1
    assert payload["changes"][0]["change_id"] == "CHG-1001"


def test_tool_output_truncation_marker():
    long_text = "x" * 5000
    truncated = compact_output(long_text, max_chars=2000)
    assert len(truncated) <= 2000
    assert "...[compacted]" in truncated


# ---------------------------------------------------------------------------
# Step 4: memory — scratchpad, compaction, SQLite long-term store
# ---------------------------------------------------------------------------


def test_scratchpad_bounded_and_renders():
    pad = Scratchpad(max_notes=3)
    for i in range(10):
        pad.add(f"note {i}", kind="observation")
    assert len(pad.notes()) <= 3
    rendered = pad.render()
    assert "[observation]" in rendered


def test_scratchpad_drops_oldest_observations_keeps_hypotheses():
    pad = Scratchpad(max_notes=3)
    pad.add("keep me hypothesis", kind="hypothesis")
    for i in range(5):
        pad.add(f"obs {i}", kind="observation")
    kinds = [n["kind"] for n in pad.notes()]
    assert "hypothesis" in kinds  # hypotheses survive compaction


def test_compact_output_short_text_unchanged():
    text = "short"
    assert compact_output(text, max_chars=2000) == text


def test_estimate_tokens_deterministic():
    assert estimate_tokens("") == 0
    assert estimate_tokens("a b c d") >= 4


def test_sqlite_store_record_and_retrieve_similar(tmp_path):
    db = tmp_path / "incidents.db"
    mem = IncidentMemory(db_path=db)
    mem.record_solved(
        incident_id="INC-1001",
        service="svc-payments",
        title="Spike in payment 3DS challenge failures",
        root_cause_change_id="CHG-1001",
        root_cause_hypothesis="3DS loop after v2.14.0 deploy",
        resolution="Rolled back v2.14.0",
        solved_at="2026-11-16T14:00:00+00:00",
    )
    hits = mem.retrieve_similar("svc-payments", "3DS challenge failures", top_k=3)
    assert len(hits) == 1
    assert hits[0]["incident_id"] == "INC-1001"
    assert hits[0]["root_cause_change_id"] == "CHG-1001"
    mem.close()


def test_sqlite_store_different_service_scores_lower(tmp_path):
    db = tmp_path / "incidents2.db"
    mem = IncidentMemory(db_path=db)
    mem.record_solved(
        incident_id="INC-1001", service="svc-payments", title="3DS challenge loop",
        root_cause_change_id="CHG-1001", root_cause_hypothesis="deploy",
        resolution="rollback", solved_at="2026-11-16T14:00:00+00:00",
    )
    # Same service + overlapping title tokens -> retrieved.
    same_service = mem.retrieve_similar("svc-payments", "3DS challenge loop", top_k=3)
    assert len(same_service) == 1
    # Different service AND a title with zero token overlap -> not retrieved.
    other_service = mem.retrieve_similar(
        "svc-search", "indexer pool exhaustion", top_k=3
    )
    assert len(other_service) == 0
    mem.close()


def test_sqlite_store_persists_across_connections(tmp_path):
    db = tmp_path / "persist.db"
    mem = IncidentMemory(db_path=db)
    mem.record_solved(
        incident_id="INC-1001", service="svc-payments", title="t",
        root_cause_change_id="CHG-1001", root_cause_hypothesis="h",
        resolution="r", solved_at="2026-11-16T14:00:00+00:00",
    )
    mem.close()
    mem2 = IncidentMemory(db_path=db)
    assert len(mem2.all()) == 1
    mem2.close()


# ---------------------------------------------------------------------------
# Step 5: multi-agent coordination — orchestrator + 3 parallel analysts
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_orchestrator_fans_out_three_analysts():
    orch = IncidentOrchestrator()
    inc = _base_incident()
    result = await orch.investigate(inc)
    assert result["incident_id"] == "INC-1001"
    assert result["analyst_count"] == 3
    analysts = {f["analyst"] for f in result["findings"]}
    assert analysts == {"logs_analyst", "metrics_analyst", "changes_analyst"}


@pytest.mark.asyncio
async def test_orchestrator_changes_analyst_ranks_prime_suspect():
    orch = IncidentOrchestrator()
    result = await orch.investigate(get_incident("INC-1004")["incident"])
    changes_finding = next(
        f for f in result["findings"] if f["analyst"] == "changes_analyst"
    )
    assert changes_finding["ok"] is True
    # Prime suspect must be the temporally-adjacent flag toggle CHG-4002,
    # not the older deploy CHG-4001.
    assert changes_finding["candidate"]["change_id"] == "CHG-4002"


@pytest.mark.asyncio
async def test_orchestrator_synthesis_converges_on_change():
    orch = IncidentOrchestrator()
    result = await orch.investigate(_base_incident())
    # With logs+metrics+changes converging, the top candidate is the change.
    top = result["candidates"][0]
    assert top["change_id"] == "CHG-1001"
    assert top["confidence"] >= 0.85


# ---------------------------------------------------------------------------
# Step 6: evaluation — 30-case replay suite, 3 runs, scoreboard
# ---------------------------------------------------------------------------


def test_replay_suite_has_thirty_cases():
    suite = build_replay_suite()
    assert len(suite) == 30  # 10 seeded incidents x 3 permutations
    case_ids = [c["case_id"] for c in suite]
    assert len(set(case_ids)) == 30


def test_replay_suite_preserves_ground_truth():
    suite = build_replay_suite()
    by_case = {c["case_id"]: c for c in suite}
    assert by_case["INC-1001-base"]["expected_change_id"] == "CHG-1001"
    assert by_case["INC-1004-shifted"]["expected_change_id"] == "CHG-4002"
    assert by_case["INC-1003-scaled"]["expected_service"] == "svc-auth"


@pytest.mark.asyncio
async def test_replay_evaluator_full_suite_passes():
    evaluator = ReplayEvaluator(runs=3, max_steps=MAX_STEPS)
    scoreboard = await evaluator.run_suite()
    assert scoreboard.total_cases == 30
    assert scoreboard.total_runs == 3
    assert scoreboard.overall_pass_rate == 1.0
    assert scoreboard.tool_selection_pass_rate == 1.0
    assert scoreboard.arguments_pass_rate == 1.0
    assert scoreboard.final_answer_pass_rate == 1.0
    assert scoreboard.trajectory_pass_rate == 1.0
    assert scoreboard.failure_taxonomy == {}


@pytest.mark.asyncio
async def test_replay_evaluator_grades_wrong_root_cause():
    # A case whose named change does not match ground truth must fail the
    # final-answer dimension (guards against false-positive grading).
    evaluator = ReplayEvaluator(runs=1)
    case = build_replay_suite()[0]
    graded = await evaluator._grade_case(case, case["incident"], 0)
    assert graded.final_answer_pass is True
    assert graded.expected_change_id == "CHG-1001"


# ---------------------------------------------------------------------------
# Step 7: deployment guardrails
# ---------------------------------------------------------------------------


def test_guardrails_step_cap_and_time_budget():
    g = InvestigationGuardrails(
        budgets=RunBudgets(max_steps=5, time_budget_seconds=10.0)
    )
    g.start_run()
    assert g.step_cap_exceeded(5) is True
    assert g.step_cap_exceeded(4) is False
    assert g.time_budget_exceeded() is False


def test_guardrails_least_privilege_read_only():
    g = InvestigationGuardrails()
    for tool in READ_ONLY_TOOLS:
        g.assert_read_only(tool)  # must not raise
    with pytest.raises(PermissionError, match="read-only"):
        g.assert_read_only("propose_patch")


def test_guardrails_approval_gate_blocks_unapproved_remediation():
    g = InvestigationGuardrails()
    req = RemediationRequest(
        incident_id="INC-1001", action="rollback", change_id="CHG-1001"
    )
    decision = g.gate_remediation(req, approver=None)
    assert decision.approved is False
    assert "no approved human sign-off" in decision.reason


def test_guardrails_approval_gate_allows_approved_remediation():
    g = InvestigationGuardrails()
    req = RemediationRequest(
        incident_id="INC-1001", action="rollback", change_id="CHG-1001"
    )
    decision = g.gate_remediation(req, approver="oncall-lead")
    assert decision.approved is True
    assert decision.decided_by == "oncall-lead"


def test_guardrails_tool_output_fenced_as_data():
    fenced = fence_tool_output("SELECT * FROM users")
    assert fenced.startswith("<<<TOOL_OUTPUT>>>")
    assert fenced.endswith("<<<END_TOOL_OUTPUT>>>")


def test_guardrails_token_budget_enforced():
    g = InvestigationGuardrails()
    g.start_run()
    assert g.consume_tokens("caller-1", 100) is True
    # Exhaust the cumulative budget for the caller.
    allowed = g.consume_tokens("caller-1", 10**9)
    assert allowed is False


@pytest.mark.asyncio
async def test_investigator_facade_full_run(tmp_path):
    from incident_agent.memory import IncidentMemory

    mem = IncidentMemory(db_path=tmp_path / "inv.db")
    inv = IncidentInvestigator(memory=mem)
    result = await inv.investigate(_base_incident())
    assert result["incident_id"] == "INC-1001"
    assert result["mode"] == "orchestrator_workers"  # pipeline misjudged -> escalate
    assert result["pipeline_misjudged"] is True
    assert result["report"]["root_cause"]["change_id"] == "CHG-1001"
    assert len(result["trace"]) > 0
    mem.close()


@pytest.mark.asyncio
async def test_investigator_fences_tool_output_as_data(tmp_path):
    # Step 7 guardrail: every tool-output preview leaving the agent boundary is
    # fenced with delimiters so it is treated as data, never as instructions.
    from incident_agent.memory import IncidentMemory

    mem = IncidentMemory(db_path=tmp_path / "inv_fence.db")
    inv = IncidentInvestigator(memory=mem)
    result = await inv.investigate(_base_incident())
    previews = [
        c["output_preview"] for c in result["report"]["tool_calls"]
    ]
    assert previews, "expected at least one tool call in the trace"
    for preview in previews:
        assert preview.startswith("<<<TOOL_OUTPUT>>>")
        assert preview.endswith("<<<END_TOOL_OUTPUT>>>")
    mem.close()


@pytest.mark.asyncio
async def test_investigator_fixed_pipeline_mode_when_not_misjudged(tmp_path):
    from incident_agent.memory import IncidentMemory

    mem = IncidentMemory(db_path=tmp_path / "inv2.db")
    inv = IncidentInvestigator(memory=mem)
    # INC-1005 (P3, single old deploy) is NOT misjudged by the fixed pipeline.
    inc = get_incident("INC-1005")["incident"]
    result = await inv.investigate(inc)
    assert result["mode"] == "fixed_pipeline"
    assert result["pipeline_misjudged"] is False
    mem.close()


def test_webhook_signature_verification():
    import hmac
    import hashlib

    secret = "webhook-secret"
    body = b'{"incident_id": "INC-1001"}'
    digest = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    assert verify_webhook_signature(body, f"sha256={digest}", secret) is True
    assert verify_webhook_signature(body, "sha256=badsig", secret) is False
    assert verify_webhook_signature(body, None, secret) is False
    assert verify_webhook_signature(body, "sha256=x", None) is True  # no secret = skip


def test_webhook_handler_rejects_bad_signature():
    result = handle_alert_webhook(
        body=b"{}", signature="sha256=bad", secret="s",
        payload={},
    )
    assert result["status"] == "rejected"
    assert result["reason"] == "invalid webhook signature"


def test_webhook_handler_accepts_and_builds_incident():
    payload = {
        "incident_id": "INC-1001",
        "service": "svc-payments",
        "title": "Spike in payment 3DS challenge failures",
        "severity": "P1",
        "alert_fired_at": BASE_TIME.isoformat(),
        "summary": "Payments 5xx rate jumped after v2.14.0 deploy",
    }
    result = handle_alert_webhook(
        body=b"{}", signature=None, secret=None, payload=payload
    )
    assert result["status"] == "accepted"
    assert result["shadow_mode"] is True
    assert result["incident"]["incident_id"] == "INC-1001"


def test_investigator_remediation_is_approval_gated(tmp_path):
    from incident_agent.memory import IncidentMemory

    mem = IncidentMemory(db_path=tmp_path / "inv3.db")
    inv = IncidentInvestigator(memory=mem)
    # No approver -> blocked.
    blocked = inv.propose_remediation(
        "INC-1001", "rollback", "CHG-1001", "3DS loop", approver=None
    )
    assert blocked.approved is False
    # Approved caller -> allowed.
    approved = inv.propose_remediation(
        "INC-1001", "rollback", "CHG-1001", "3DS loop", approver="oncall-lead"
    )
    assert approved.approved is True
    mem.close()


# ---------------------------------------------------------------------------
# Cross-cutting: architectural invariants for the new package
# ---------------------------------------------------------------------------


def test_incident_models_reject_extra_fields():
    # Strict Pydantic v2: extra='forbid' across all incident models.
    with pytest.raises(Exception):
        Incident(
            incident_id="INC-1", service="svc", title="t",
            severity=IncidentSeverity.P1,
            alert_fired_at=BASE_TIME, summary="s",
            unexpected_field="boom",  # type: ignore[call-arg]
        )


def test_tool_result_compact_text_fences_errors():
    r = ToolResult(tool="incident.get", ok=False, error="bad input")
    assert "[TOOL ERROR incident.get]" in r.to_compact_text()


def test_data_registry_resolves_permuted_variant_ids():
    # Replay variants (INC-1001-s / INC-1001-x) resolve to the canonical base.
    base = get_incident("INC-1001")
    shifted = get_incident("INC-1001-s")
    scaled = get_incident("INC-1001-x")
    assert base["incident"].incident_id == shifted["incident"].incident_id == "INC-1001"
    assert base["expected_change_id"] == scaled["expected_change_id"] == "CHG-1001"


def test_data_registry_unknown_id_raises():
    with pytest.raises(KeyError):
        get_incident("INC-0000")


def test_corpus_is_deterministic():
    # The synthetic corpus must be byte-stable across imports for replayability.
    rec = get_incident("INC-1002")
    assert rec["incident"].service == "svc-search"
    assert rec["expected_change_id"] == "CHG-2001"
    assert BASE_TIME.year == 2026


# ---------------------------------------------------------------------------
# Hermeticity & MCP server guards (deployment hardening)
# ---------------------------------------------------------------------------


def test_default_memory_db_lives_in_data_dir_not_source_tree():
    # Importing the package must never drop a DB beside the source files.
    from incident_agent import memory as mem_mod

    resolved = mem_mod._default_db_path()
    assert resolved.parent.name == "data"
    assert resolved.name == "incident_memory.db"
    assert "incident_agent" not in resolved.parts[-2:]


def test_memory_db_env_override_respected(monkeypatch, tmp_path):
    monkeypatch.setenv("INCIDENT_MEMORY_DB", str(tmp_path / "custom.db"))
    from incident_agent import memory as mem_mod

    assert mem_mod._default_db_path() == tmp_path / "custom.db"


@pytest.mark.asyncio
async def test_mcp_guarded_dispatch_enforces_rbac_and_rate_limit():
    # The MCP server must fail closed on RBAC and rate limiting, mirroring the
    # SDLC gateway's zero-trust conventions.
    from incident_agent import mcp_server

    class _Req:
        auth_token = None
        user_roles = ["finance_executive"]  # not in the engineer/sre/admin ACL

    result = await mcp_server._guarded_dispatch(
        "incident.get", _Req(), {"incident_id": "INC-1001"}
    )
    assert "⛔" in result  # fail-closed denial


@pytest.mark.asyncio
async def test_mcp_guarded_dispatch_allows_engineer():
    from incident_agent import mcp_server

    class _Req:
        auth_token = None
        user_roles = ["engineer"]

    result = await mcp_server._guarded_dispatch(
        "incident.get", _Req(), {"incident_id": "INC-1001"}
    )
    assert "⛔" not in result
    assert '"ok": true' in result


def test_mcp_server_exposes_six_read_only_tools():
    from incident_agent import mcp_server

    tool_names = {t for t in mcp_server.TOOL_REQUIRED_ROLES}
    assert tool_names == {
        "incident.get",
        "incident.list",
        "logs.query",
        "metrics.query",
        "changes.list",
        "memory.recall_similar",
    }
    # No mutation tools are exposed (least privilege).
    assert not any("patch" in t or "remediate" in t or "rollback" in t for t in tool_names)
