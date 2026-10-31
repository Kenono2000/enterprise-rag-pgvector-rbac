"""
tests/test_agent.py
-------------------
Consolidated unit and lifecycle tests for the autonomous SDLC agent,
including guardrails, AST security, schema drift detection, context compaction,
webhook parsing, and LangGraph workflow.
"""

import subprocess
import pytest
from pydantic import BaseModel

from agent import (
    PolicyEngine,
    parse_github_webhook,
    verify_github_signature,
    LangGraphSDLCWorkflow,
    PatchProposal,
    ApprovalCard,
    TestTriagerSubagent,
    CrossModelJudgeSubagent,
    CrewAgentSpec,
    CrewTaskOutput,
    SDLCCrewOrchestrator,
    HermesSkillArtifact,
    HermesTrajectoryRecord,
    HermesSkillSynthesizer,
    GroundingGuardrail,
    compact_agent_context,
)
from app.mcp.gateway import MCPSearchRequest, MCPPatchRequest
from app.main import RAGQueryRequest


def git(root, *args):
    return subprocess.run(
        ["git", *args], cwd=root, check=True, capture_output=True, text=True
    )


# ---------------------------------------------------------------------------
# Guardrails & AST Policy Tests
# ---------------------------------------------------------------------------

def test_secret_scanning():
    content_with_secret = "api_key = 'sk-abcdef1234567890abcdef1234567890'"
    violations = PolicyEngine.scan_for_secrets(content_with_secret)
    assert len(violations) > 0
    assert "sk-" in violations[0]

    safe_content = "api_key = 'safe_value'"
    violations = PolicyEngine.scan_for_secrets(safe_content)
    assert len(violations) == 0


def test_ast_verification():
    dangerous_code = "eval('os.system(\"rm -rf /\")')"
    violations = PolicyEngine.verify_ast(dangerous_code)
    assert any("eval" in v for v in violations)

    dunder_import = "x = __import__('os')"
    violations = PolicyEngine.verify_ast(dunder_import)
    assert any("__import__" in v for v in violations)

    os_system_code = "import os\nos.system('whoami')"
    violations = PolicyEngine.verify_ast(os_system_code)
    assert any("os.system" in v for v in violations)

    shell_true_code = "import subprocess\nsubprocess.run('ls', shell=True)"
    violations = PolicyEngine.verify_ast(shell_true_code)
    assert any("shell=True" in v for v in violations)

    pickle_code = "import pickle\npickle.loads(b'data')"
    violations = PolicyEngine.verify_ast(pickle_code)
    assert any("pickle.loads" in v for v in violations)

    assert PolicyEngine.verify_protected_path("agent/guardrails.py") != []
    assert PolicyEngine.verify_protected_path(".env") != []
    assert PolicyEngine.verify_protected_path("app/main.py") == []

    safe_code = "x = 1 + 1\nprint(x)"
    violations = PolicyEngine.verify_ast(safe_code)
    assert len(violations) == 0


def test_schema_drift_guardrail():
    assert PolicyEngine.verify_schema_drift(RAGQueryRequest, {"question"}) == []
    assert PolicyEngine.verify_schema_drift(MCPSearchRequest, {"question"}) == []
    assert PolicyEngine.verify_schema_drift(MCPPatchRequest, {"branch_name", "patch_content"}) == []

    class LaxModel(BaseModel):
        query: str

    drift_violations = PolicyEngine.verify_schema_drift(LaxModel, {"query", "missing_field"})
    assert len(drift_violations) == 2
    assert any("extra='forbid'" in v for v in drift_violations)
    assert any("missing_field" in v for v in drift_violations)


def test_prefix_caching_and_context_compaction():
    bundle = GroundingGuardrail.build_prefix_cached_prompt(
        context_chunks_text="[Doc: Policy, Chunk 0]: Strict RBAC.",
        user_question="What is the policy?",
    )
    assert len(bundle["prefix_hash"]) == 16
    assert bundle["static_prefix_tokens"] > 10
    assert bundle["prompt"].startswith("You are a Zero-Trust Enterprise Knowledge Assistant.")

    compacted = compact_agent_context(
        raw_trace="line1\n" * 1000 + "E   AssertionError: expected 200",
        triage_summary={
            "concise_summary": "[ASSERTION_FAILURE] tests/test_rag.py -> AssertionError",
            "failing_targets": ["tests/test_rag.py::test_query"],
        },
        max_chars=200,
    )
    assert "[Flash Test-Triager Summary]:" in compacted
    assert "[Failing Targets]: tests/test_rag.py::test_query" in compacted
    assert "AssertionError: expected 200" in compacted


@pytest.mark.asyncio
async def test_evaluate_patch():
    result = await PolicyEngine.evaluate_patch(
        file_path="src/main.py",
        content="def hello():\n    return 'world'",
        applied_adrs=["ADR-001"],
        test_trace="All tests passed",
    )
    assert result.passed is True
    assert "ADR-001" in result.audit_summary
    assert "✅ PASSED" in result.audit_summary


# ---------------------------------------------------------------------------
# Webhook Parser & Signature Tests
# ---------------------------------------------------------------------------

def test_webhook_parsing():
    payload = {
        "issue": {
            "number": 123,
            "title": "Fix bug in auth",
            "body": "The auth module is failing",
        },
        "repository": {"full_name": "org/repo"},
    }
    event = parse_github_webhook(payload)
    assert event.issue_id == "123"
    assert event.source == "github"
    assert event.title == "Fix bug in auth"


def test_webhook_signature():
    secret = "test-secret"
    body = b'{"hello": "world"}'
    import hmac, hashlib
    digest = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    valid_sig = f"sha256={digest}"

    assert verify_github_signature(body, valid_sig, secret) is True
    assert verify_github_signature(body, "sha256=invalid", secret) is False
    assert verify_github_signature(body, None, None) is True


# ---------------------------------------------------------------------------
# LangGraph Workflow Integration Test
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_langgraph_workflow_execution(tmp_path):
    git(tmp_path, "init")
    git(tmp_path, "config", "user.email", "test@example.com")
    git(tmp_path, "config", "user.name", "Test")
    (tmp_path / "value.py").write_text("VALUE = 1\n", encoding="utf-8")
    (tmp_path / "test_value.py").write_text(
        "from value import VALUE\n\ndef test_value():\n    assert VALUE == 2\n",
        encoding="utf-8",
    )
    git(tmp_path, "add", ".")
    git(tmp_path, "commit", "-m", "initial")

    payload = {
        "issue": {"number": 123, "title": "Fix value", "body": "Update the value."},
        "repository": {"full_name": "org/repo"},
        "patches": [{"file_path": "value.py", "content": "VALUE = 2\n"}],
    }

    workflow = LangGraphSDLCWorkflow(
        sandbox_root=str(tmp_path),
        test_command="python -m pytest -q",
        push=False,
    )
    result = await workflow.run(payload)

    assert result["status"] == "completed"
    assert "AGENT-123" in result["branch"]
    assert result["pushed"] is False
    assert result["subagent_routing"]["triager"] == "flash (test-triager)"
    assert result["subagent_routing"]["judge"] == "pro (cross-model-judge)"
    assert result["judge_verdict"]["verdict"] == "PASS"
    assert result["judge_verdict"]["score"] == 1.0
    assert len(result["crew_trace"]) == 3
    assert [step["agent_name"] for step in result["crew_trace"]] == [
        "arch-synthesizer",
        "cross-model-judge",
        "test-triager",
    ]
    assert result["hermes_skill"]["skill_name"] == "hermes-issue-123-fix-value"
    assert "---\nname: hermes-issue-123-fix-value" in result["hermes_skill"]["markdown_content"]
    assert result["hermes_trajectory"]["format"] == "sharegpt"
    assert len(result["hermes_trajectory"]["conversations"]) == 4
    assert "Fix value" in git(tmp_path, "log", "-1", "--format=%s").stdout


def test_crewai_orchestrator_and_hermes_synthesizer(tmp_path):
    assert PolicyEngine.verify_schema_drift(
        CrewAgentSpec, {"name", "role", "goal", "backstory", "model_tier"}
    ) == []
    assert PolicyEngine.verify_schema_drift(
        CrewTaskOutput, {"agent_name", "role", "task_name", "model_tier", "summary"}
    ) == []
    assert PolicyEngine.verify_schema_drift(
        HermesSkillArtifact, {"skill_name", "skill_path", "markdown_content"}
    ) == []
    assert PolicyEngine.verify_schema_drift(
        HermesTrajectoryRecord, {"issue_id", "branch"}
    ) == []

    crew_specs = SDLCCrewOrchestrator.get_crew_specs()
    assert set(crew_specs.keys()) == {"arch-synthesizer", "cross-model-judge", "test-triager"}
    role_prompt = SDLCCrewOrchestrator.format_role_prompt(
        SDLCCrewOrchestrator.ARCHITECT, "Fix OAuth PKCE state TTL"
    )
    assert "[CrewAI Role]: Principal SDLC Architect" in role_prompt
    assert "Fix OAuth PKCE state TTL" in role_prompt

    event = parse_github_webhook(
        {
            "issue": {"number": 42, "title": "Harden PKCE cookie", "body": "Ensure 15m idle TTL."},
            "repository": {"full_name": "org/repo"},
        }
    )
    patches = [PatchProposal(file_path="app/auth/pkce.py", content="IDLE_TTL = 900\n")]
    skill = HermesSkillSynthesizer.synthesize_skill(
        event=event,
        patches=patches,
        judge_verdict={"score": 1.0},
        triage_summary={"concise_summary": "All tests passed."},
        sandbox_root=tmp_path,
        persist=True,
    )
    assert skill.persisted is True
    skill_file = tmp_path / skill.skill_path
    assert skill_file.exists()
    assert "IDLE_TTL = 900" in skill_file.read_text(encoding="utf-8")

    trajectory = HermesSkillSynthesizer.export_rl_trajectory(
        event=event,
        branch="feature/AGENT-42-harden-pkce-cookie",
        patches=patches,
        judge_verdict={"score": 1.0},
        triage_summary={"concise_summary": "All tests passed."},
        repairs_used=1,
    )
    assert trajectory.format == "sharegpt"
    assert trajectory.repairs_used == 1
    assert trajectory.reward == 0.75
    assert trajectory.token_efficiency_score == 0.8
    assert "[Atropos Reward: 0.75]" in trajectory.conversations[3]["value"]
    assert trajectory.conversations[0]["from"] == "system"
    assert trajectory.conversations[2]["from"] == "gpt"

    # Verify optional crewai SDK adapter fallback and mocked crewai runtime bridge
    native_crew = SDLCCrewOrchestrator.build_crewai_crew(event.title, event.description)
    assert native_crew["runtime"] in ("native_pydantic", "crewai_sdk")
    kickoff_res = SDLCCrewOrchestrator.kickoff_crew(event.title, event.description)
    assert len(kickoff_res["tasks"]) == 3

    import os
    import sys
    import types
    fake_crewai = types.ModuleType("crewai")
    fake_crewai.Agent = lambda **kw: kw
    fake_crewai.Task = lambda **kw: kw

    class _FakeProcess:
        sequential = "sequential"

    class _FakeCrew:
        def __init__(self, **kw):
            self.kw = kw

        def kickoff(self):
            return "CrewAI executed for Harden PKCE cookie"

    fake_crewai.Process = _FakeProcess
    fake_crewai.Crew = _FakeCrew
    sys.modules["crewai"] = fake_crewai
    os.environ["USE_CREWAI_SDK"] = "true"
    try:
        sdk_crew = SDLCCrewOrchestrator.build_crewai_crew(event.title, event.description)
        assert sdk_crew["runtime"] == "crewai_sdk"
        assert len(sdk_crew["agents"]) == 3
        assert len(sdk_crew["tasks"]) == 3
        sdk_kickoff = SDLCCrewOrchestrator.kickoff_crew(event.title, event.description)
        assert sdk_kickoff["runtime"] == "crewai_sdk"
        assert sdk_kickoff["status"] == "completed"
        assert "Harden PKCE cookie" in sdk_kickoff["output"]
    finally:
        sys.modules.pop("crewai", None)
        os.environ.pop("USE_CREWAI_SDK", None)

    from agent.__main__ import run_cli
    assert run_cli(["status"]) == 0
    assert run_cli(["crew", "Harden PKCE cookie", "15m idle TTL"]) == 0
    assert run_cli(["recall", "PKCE"]) == 0
    assert run_cli(["synthesize", "Harden PKCE cookie"]) == 0


def test_flash_test_triager_subagent():
    triager = TestTriagerSubagent()
    assert triager.model_tier == "flash"
    assert triager.name == "test-triager"

    passed_res = triager.classify_failure(0, "10 passed in 0.42s")
    assert passed_res.failure_category == "none"

    syntax_res = triager.classify_failure(
        1,
        "FAILED tests/test_auth.py::test_pkce - SyntaxError: invalid syntax",
    )
    assert syntax_res.failure_category == "compilation_error"
    assert "tests/test_auth.py::test_pkce" in syntax_res.failing_targets

    assert_res = triager.classify_failure(
        1,
        "FAILED tests/test_rag.py::test_rbac\nE   AssertionError: expected 200 got 403",
    )
    assert assert_res.failure_category == "assertion_failure"
    assert "tests/test_rag.py::test_rbac" in assert_res.failing_targets

    timeout_res = triager.classify_failure(
        1,
        "FAILED tests/test_db.py::test_pool - asyncio.TimeoutError: pool timed out",
    )
    assert timeout_res.failure_category == "timeout"


@pytest.mark.asyncio
async def test_pro_cross_model_judge_subagent():
    judge = CrossModelJudgeSubagent()
    assert judge.model_tier == "pro"
    assert judge.name == "cross-model-judge"

    safe_verdict = await judge.evaluate_diff(
        [PatchProposal(file_path="app/utils.py", content="def add(a: int, b: int) -> int:\n    return a + b\n")],
        requirements="Add integer helper",
    )
    assert safe_verdict.verdict == "PASS"
    assert safe_verdict.passed is True
    assert safe_verdict.score == 1.0
    assert "app/utils.py:L1-L2" in safe_verdict.line_references

    unsafe_verdict = await judge.evaluate_diff(
        [PatchProposal(file_path="app/bad.py", content="x = 1\neval('os.system(\"id\")')\n")],
        requirements="Check security gate",
    )
    assert unsafe_verdict.verdict == "FAIL"
    assert unsafe_verdict.passed is False
    assert unsafe_verdict.score < 1.0
    assert "app/bad.py:L2" in unsafe_verdict.line_references


@pytest.mark.asyncio
async def test_production_rollback_judge_healing_and_hitl(tmp_path):
    assert PolicyEngine.verify_schema_drift(ApprovalCard, {"reason"}) == []

    git(tmp_path, "init")
    git(tmp_path, "config", "user.email", "test@example.com")
    git(tmp_path, "config", "user.name", "Test")
    (tmp_path / "value.py").write_text("VALUE = 1\n", encoding="utf-8")
    (tmp_path / "test_value.py").write_text(
        "from value import VALUE\n\ndef test_value():\n    assert VALUE == 2\n",
        encoding="utf-8",
    )
    git(tmp_path, "add", ".")
    git(tmp_path, "commit", "-m", "initial")

    # 1. Secret leak triggers immediate atomic rollback restoring value.py to VALUE = 1
    bad_secret_payload = {
        "issue": {"number": 201, "title": "Leak secret", "body": "Bad patch"},
        "repository": {"full_name": "org/repo"},
        "patches": [
            {
                "file_path": "value.py",
                "content": "VALUE = 'sk-abcdef1234567890abcdef1234567890'\n",
            }
        ],
    }
    wf_rollback = LangGraphSDLCWorkflow(
        sandbox_root=str(tmp_path),
        test_command="python -c \"import value; assert value.VALUE == 2\"",
        push=False,
    )
    with pytest.raises(ValueError, match="Security gate failed"):
        await wf_rollback.run(bad_secret_payload)
    assert (tmp_path / "value.py").read_text(encoding="utf-8") == "VALUE = 1\n"

    # 2. Judge-driven self-healing repairs an AST violation and persists a Hermes skill
    heal_payload = {
        "issue": {"number": 202, "title": "Heal AST violation", "body": "Fix value safely"},
        "repository": {"full_name": "org/repo"},
        "patches": [{"file_path": "value.py", "content": "import os\nos.system('id')\n"}],
        "repair_patches": [{"file_path": "value.py", "content": "VALUE = 2\n"}],
    }
    wf_heal = LangGraphSDLCWorkflow(
        sandbox_root=str(tmp_path),
        test_command="python -c \"import value; assert value.VALUE == 2\"",
        push=False,
        persist_hermes_skill=True,
    )
    heal_result = await wf_heal.run(heal_payload)
    assert heal_result["status"] == "completed"
    assert (tmp_path / "value.py").read_text(encoding="utf-8") == "VALUE = 2\n"
    assert heal_result["hermes_skill"]["persisted"] is True

    # 3. Closed-loop Hermes skill recall + OpenCrew HITL high-risk approval gate
    recalled = HermesSkillSynthesizer.recall_relevant_skills(tmp_path, "Heal AST violation")
    assert len(recalled) == 1

    hitl_payload = {
        "issue": {"number": 203, "title": "Update auth PKCE", "body": "Heal AST violation in auth"},
        "repository": {"full_name": "org/repo"},
        "patches": [{"file_path": "app/auth/config.py", "content": "AUTH_TIMEOUT = 900\n"}],
    }
    wf_hitl = LangGraphSDLCWorkflow(
        sandbox_root=str(tmp_path),
        test_command="python -c \"assert True\"",
        push=False,
        require_hitl_for_high_risk=True,
    )
    hitl_result = await wf_hitl.run(hitl_payload)
    assert hitl_result["status"] == "pending_approval"
    assert hitl_result["checkpoint_backend"] == "PostgresSaver"
    assert hitl_result["approval_card"]["risk_tier"] == "high_risk"
    assert hitl_result["approval_card"]["requires_human_approval"] is True
    assert hitl_result["interrupted"] is True
    assert len(hitl_result["recalled_skills"]) == 1

    # 4. Multi-worker crash-resilient resumption via PostgresSaver
    wf_worker_2 = LangGraphSDLCWorkflow(
        sandbox_root=str(tmp_path),
        test_command="python -c \"assert True\"",
        push=False,
    )
    resumed = await wf_worker_2.resume_from_checkpoint(
        thread_id=hitl_result["thread_id"],
        human_approved=True,
    )
    assert resumed["status"] == "completed"
    assert resumed["checkpoint_backend"] == "PostgresSaver"
    assert resumed["resumed_from"] == hitl_result["checkpoint_id"]
    assert resumed["approval_card"]["status"] == "auto_approved"

    # 5. Checkpoint execution history time-travel inspection & CLI
    history = await wf_worker_2.get_execution_history(hitl_result["thread_id"])
    assert len(history) >= 1

    from agent.__main__ import run_cli
    assert run_cli(["checkpoints", hitl_result["thread_id"]]) == 0


@pytest.mark.asyncio
async def test_langgraph_workflow_parallel_verify(tmp_path):
    git(tmp_path, "init")
    git(tmp_path, "config", "user.email", "test@example.com")
    git(tmp_path, "config", "user.name", "Test")
    (tmp_path / "value.py").write_text("VALUE = 1\n", encoding="utf-8")
    (tmp_path / "test_value.py").write_text(
        "from value import VALUE\n\ndef test_value():\n    assert VALUE == 2\n", encoding="utf-8"
    )
    git(tmp_path, "add", ".")
    git(tmp_path, "commit", "-m", "initial")
    payload = {
        "issue": {"number": 124, "title": "Fix value", "body": "Update the value."},
        "repository": {"full_name": "org/repo"},
        "patches": [{"file_path": "value.py", "content": "VALUE = 2\n"}],
    }
    workflow = LangGraphSDLCWorkflow(
        sandbox_root=str(tmp_path), test_command="python -m pytest -q", push=False, parallel_verify=True,
    )
    result = await workflow.run(payload)
    assert result["status"] == "completed"
    assert {s["agent_name"] for s in result["crew_trace"]} == {
        "arch-synthesizer", "cross-model-judge", "test-triager",
    }
    assert len(result["crew_trace"]) == 3


def test_crewai_flow_builder_plan():
    bundle = SDLCCrewOrchestrator.build_crewai_flow(
        lambda: "p", lambda: "a", lambda: "t", lambda: "j"
    )
    assert bundle["plan"]["parallel"] == ["audit_patches", "run_tests"]
    assert bundle["runtime"] in ("crewai_flow", "native_pydantic")
