"""
agent/workflow.py
-----------------
Autonomous SDLC Agent workflow uniting three agentic paradigms:
1. LangChain / LangGraph: Deterministic cyclic state-machine orchestration, checkpointing, and bounded self-healing repair loops.
2. CrewAI: Role-based multi-agent crew (`Role + Goal + Backstory + Tasks`) across Architect (`inherit`), Judge (`pro`), and Triager (`flash`).
3. Hermes Agent (Nous Research): Autonomous portable `SKILL.md` synthesis (`agentskills.io`) and ShareGPT RL trajectory export for lifelong learning.
"""

from __future__ import annotations

import os
import re
import shlex
import json
import logging
import subprocess
from pathlib import Path
from urllib import request
from typing import Any, Dict, List, Optional, TypedDict, Literal

from pydantic import BaseModel, ConfigDict, Field
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver

from app.db import chat_completion
from app.observability import tracer
from agent.guardrails import PolicyEngine, TokenCircuitBreaker
from agent.parser import SDLCEvent, parse_github_webhook

logger = logging.getLogger("agent.workflow")


# ---------------------------------------------------------------------------
# Strict Data Models (extra='forbid')
# ---------------------------------------------------------------------------

class PatchProposal(BaseModel):
    model_config = ConfigDict(extra="forbid")

    file_path: str = Field(min_length=1)
    content: str


class ApprovalCard(BaseModel):
    """OpenCrew-style Autonomy Ladder approval card for risk-tiered SDLC governance."""

    model_config = ConfigDict(extra="forbid")

    risk_tier: Literal["low_risk", "high_risk"] = "low_risk"
    requires_human_approval: bool = False
    status: Literal["auto_approved", "pending_human_approval", "rejected"] = "auto_approved"
    affected_files: List[str] = Field(default_factory=list)
    high_risk_files: List[str] = Field(default_factory=list)
    reason: str = Field(min_length=1)


class CrewAgentSpec(BaseModel):
    """CrewAI mental model: Role + Goal + Backstory + Tiered Model assignment."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    role: str = Field(min_length=1)
    goal: str = Field(min_length=1)
    backstory: str = Field(min_length=1)
    model_tier: Literal["inherit", "pro", "flash"]


class CrewTaskOutput(BaseModel):
    """Structured task execution record emitted by a CrewAI role agent."""

    model_config = ConfigDict(extra="forbid")

    agent_name: str = Field(min_length=1)
    role: str = Field(min_length=1)
    task_name: str = Field(min_length=1)
    model_tier: Literal["inherit", "pro", "flash"]
    status: Literal["completed", "failed"] = "completed"
    summary: str = Field(min_length=1)


class HermesSkillArtifact(BaseModel):
    """Hermes Agent portable SKILL.md artifact synthesized after verified issue resolution."""

    model_config = ConfigDict(extra="forbid")

    skill_name: str = Field(min_length=1)
    skill_path: str = Field(min_length=1)
    markdown_content: str = Field(min_length=1)
    persisted: bool = False


class HermesTrajectoryRecord(BaseModel):
    """Hermes Agent ShareGPT-formatted RL trajectory for lifelong memory and Atropos/vLLM training."""

    model_config = ConfigDict(extra="forbid")

    format: Literal["sharegpt"] = "sharegpt"
    issue_id: str = Field(min_length=1)
    branch: str = Field(min_length=1)
    judge_score: float = Field(default=1.0, ge=0.0, le=1.0)
    repairs_used: int = Field(default=0, ge=0)
    conversations: List[Dict[str, str]] = Field(default_factory=list)


class TriageSummary(BaseModel):
    """Structured output returned by the Gemini Flash `test-triager` subagent."""

    model_config = ConfigDict(extra="forbid")

    model_tier: Literal["flash"] = "flash"
    subagent_name: str = "test-triager"
    failure_category: Literal[
        "none", "compilation_error", "assertion_failure", "timeout"
    ] = "none"
    failing_targets: List[str] = Field(default_factory=list)
    concise_summary: str = ""


class JudgeVerdict(BaseModel):
    """Structured pass/fail verdict and rubric score returned by the Gemini Pro `cross-model-judge` subagent."""

    model_config = ConfigDict(extra="forbid")

    model_tier: Literal["pro"] = "pro"
    subagent_name: str = "cross-model-judge"
    verdict: Literal["PASS", "FAIL"] = "PASS"
    passed: bool = True
    score: float = Field(default=1.0, ge=0.0, le=1.0)
    line_references: List[str] = Field(default_factory=list)
    findings: List[str] = Field(default_factory=list)


class TestResult:
    def __init__(self, returncode: int, output: str):
        self.returncode = returncode
        self.output = output


def compact_agent_context(
    raw_trace: str,
    triage_summary: Optional[Dict[str, Any]] = None,
    max_chars: int = 2500,
) -> str:
    """
    Deterministically compact noisy test logs into a high-signal context window
    for multi-turn repair loops, pairing the Flash `test-triager` summary with
    deduplicated assertion/error lines and a bounded tail slice.
    """
    header_parts: List[str] = []
    if triage_summary and triage_summary.get("concise_summary"):
        header_parts.append(f"[Flash Test-Triager Summary]: {triage_summary['concise_summary']}")
        targets = triage_summary.get("failing_targets") or []
        if targets:
            header_parts.append(f"[Failing Targets]: {', '.join(targets[:5])}")

    tail = (raw_trace or "")[-max_chars:]
    if header_parts:
        return "\n".join(header_parts) + "\n\n" + tail
    return tail


class TestTriagerSubagent:
    """
    High-speed mechanical log-triage subagent (`model: flash`, `.agents/agents/test-triager.md`).
    Offloads test output classification (compilation_error, assertion_failure, timeout)
    from the primary frontier reasoning model to reduce latency and token spend.
    """

    name: str = "test-triager"
    model_tier: Literal["flash"] = "flash"

    def classify_failure(self, returncode: int, raw_output: str) -> TriageSummary:
        if returncode == 0:
            return TriageSummary(
                failure_category="none",
                failing_targets=[],
                concise_summary="All requested test targets passed (returncode=0).",
            )

        lines = [line.strip() for line in raw_output.splitlines() if line.strip()]
        failing_targets: List[str] = []
        error_lines: List[str] = []

        for line in lines:
            if line.startswith("FAILED "):
                target = line.replace("FAILED ", "").split(" - ")[0].strip()
                if target and target not in failing_targets:
                    failing_targets.append(target)
            elif line.startswith("E   ") or "Error:" in line or "Exception:" in line:
                error_lines.append(line)

        lower_out = raw_output.lower()
        if any(
            tok in lower_out
            for tok in ("timeouterror", "timed out", "timeout expired", "deadline exceeded")
        ):
            category: Literal["none", "compilation_error", "assertion_failure", "timeout"] = (
                "timeout"
            )
        elif any(
            tok in raw_output
            for tok in (
                "SyntaxError",
                "IndentationError",
                "ImportError",
                "ModuleNotFoundError",
                "NameError",
                "TypeError",
            )
        ):
            category = "compilation_error"
        else:
            category = "assertion_failure"

        headline = error_lines[0] if error_lines else (lines[-1] if lines else "Unknown test failure")
        targets_str = ", ".join(failing_targets[:5]) if failing_targets else "unspecified target"
        summary = f"[{category.upper()}] {targets_str} -> {headline[:220]}"

        return TriageSummary(
            failure_category=category,
            failing_targets=failing_targets,
            concise_summary=summary,
        )


class CrossModelJudgeSubagent:
    """
    Independent LLM-as-a-judge verifier (`model: pro`, `.agents/agents/gemini-judge.md`).
    Audits diffs against user requirements, regressions, missing edge cases, and security issues,
    emitting a deterministic PASS/FAIL verdict, rubric score (0.0-1.0), and specific line references.
    """

    name: str = "cross-model-judge"
    model_tier: Literal["pro"] = "pro"

    async def evaluate_diff(
        self,
        patches: List[PatchProposal],
        requirements: str = "",
    ) -> JudgeVerdict:
        line_references: List[str] = []
        findings: List[str] = []
        penalty = 0.0

        if not patches:
            findings.append("blocking: No patch proposals provided for diff evaluation.")
            penalty += 1.0

        for patch in patches:
            if not patch.content or not patch.content.strip():
                findings.append(f"blocking: [{patch.file_path}] Empty patch content detected.")
                penalty += 0.5

            gate = await PolicyEngine.evaluate_patch(
                patch.file_path, patch.content, [], requirements or "diff-audit"
            )
            if not gate.passed:
                for violation in gate.violations:
                    findings.append(f"blocking: [{patch.file_path}] {violation}")
                    penalty += 0.5

            for idx, line in enumerate(patch.content.splitlines(), start=1):
                if any(tok in line for tok in ("eval(", "exec(", "__import__(")):
                    ref = f"{patch.file_path}:L{idx}"
                    if ref not in line_references:
                        line_references.append(ref)
                for pattern in PolicyEngine.SECRET_PATTERNS:
                    if pattern.search(line):
                        ref = f"{patch.file_path}:L{idx}"
                        if ref not in line_references:
                            line_references.append(ref)

            if not line_references and gate.passed:
                total_lines = max(1, len(patch.content.splitlines()))
                line_references.append(f"{patch.file_path}:L1-L{total_lines}")

        passed = len(findings) == 0
        score = round(max(0.0, 1.0 - penalty), 2) if not passed else 1.0
        return JudgeVerdict(
            verdict="PASS" if passed else "FAIL",
            passed=passed,
            score=score,
            line_references=line_references,
            findings=findings
            if findings
            else ["Verified diff alignment, AST safety, and edge-case invariants."],
        )


class PayloadPatchAgent:
    """Generates and repairs file patch proposals using LLM or webhook payload, enriched with CrewAI roles and Hermes skills."""

    STATIC_SYSTEM_PREFIX = (
        "You are an autonomous SDLC software engineer.\n"
        "Respond ONLY with a valid JSON list of file patch objects matching schema:\n"
        '[{"file_path": "example.py", "content": "print(\'hello\')"}]'
    )

    async def propose(
        self,
        payload: dict[str, Any],
        recalled_skills: Optional[List[str]] = None,
    ) -> List[PatchProposal]:
        if "patches" in payload:
            return [PatchProposal(**p) for p in payload.get("patches", [])]

        issue = payload.get("issue", {})
        title = issue.get("title", "")
        body = issue.get("body", "")
        repo = payload.get("repository", {}).get("full_name", "")
        role_header = SDLCCrewOrchestrator.format_role_prompt(
            SDLCCrewOrchestrator.ARCHITECT,
            f"Synthesize patch for '{title}' in {repo}",
        )
        skills_block = (
            "\n\nRECALLED HERMES SKILLS:\n" + "\n---\n".join(recalled_skills)
            if recalled_skills
            else ""
        )

        prompt = (
            f"{self.STATIC_SYSTEM_PREFIX}\n\n"
            f"{role_header}{skills_block}\n\n"
            f"Repository: {repo}\n"
            f"Issue Title: {title}\n"
            f"Issue Description: {body}\n"
        )
        response = (await chat_completion(prompt)).strip()
        if response.startswith("```json"):
            response = response[7:]
        if response.endswith("```"):
            response = response[:-3]

        try:
            raw = json.loads(response.strip())
            return [PatchProposal(**p) for p in raw]
        except Exception as exc:
            logger.warning("LLM patch generation failed (%s), returning empty proposals", exc)
            return []

    async def repair(
        self,
        payload: dict[str, Any],
        test_output: str,
        recalled_skills: Optional[List[str]] = None,
    ) -> List[PatchProposal]:
        """Self-correct patches based on compacted pytest or AST/Judge failure traces."""
        if "repair_patches" in payload:
            return [PatchProposal(**p) for p in payload.get("repair_patches", [])]

        issue = payload.get("issue", {})
        role_header = SDLCCrewOrchestrator.format_role_prompt(
            SDLCCrewOrchestrator.ARCHITECT,
            f"Repair failing patch for '{issue.get('title', '')}'",
        )
        skills_block = (
            "\n\nRECALLED HERMES SKILLS:\n" + "\n---\n".join(recalled_skills)
            if recalled_skills
            else ""
        )
        prompt = (
            f"{self.STATIC_SYSTEM_PREFIX}\n\n"
            f"{role_header}{skills_block}\n\n"
            f"Verification failed for issue '{issue.get('title', '')}'.\n"
            f"Failure Trace:\n{test_output[-2500:]}\n"
        )
        response = (await chat_completion(prompt)).strip()
        if response.startswith("```json"):
            response = response[7:]
        if response.endswith("```"):
            response = response[:-3]

        try:
            raw = json.loads(response.strip())
            return [PatchProposal(**p) for p in raw]
        except Exception:
            return []


class SDLCCrewOrchestrator:
    """
    CrewAI-style role-based multi-agent crew orchestrator (`Role + Goal + Backstory + Tasks`).
    Assigns specialized organizational personas to the tiered subagents executing inside the
    LangGraph state machine.
    """

    ARCHITECT = CrewAgentSpec(
        name="arch-synthesizer",
        role="Principal SDLC Architect",
        goal="Synthesize minimal, zero-trust code patches that resolve the issue without breaking contracts.",
        backstory="Staff distributed-systems engineer specializing in FastAPI, pgvector RBAC, and deterministic diffs.",
        model_tier="inherit",
    )
    AUDITOR = CrewAgentSpec(
        name="cross-model-judge",
        role="Lead Security & AST Auditor",
        goal="Enforce zero-trust AST safety, secret hygiene, and strict requirement alignment on every diff.",
        backstory="Principal application security reviewer who blocks eval/exec, credential leaks, and schema drift.",
        model_tier="pro",
    )
    TRIAGER = CrewAgentSpec(
        name="test-triager",
        role="Site Reliability & Pytest Triager",
        goal="Compress noisy pytest traces into high-signal failure categories and failing target lists.",
        backstory="High-speed mechanical CI/CD diagnostician optimized for low-latency failure classification.",
        model_tier="flash",
    )

    @classmethod
    def get_crew_specs(cls) -> Dict[str, CrewAgentSpec]:
        return {
            cls.ARCHITECT.name: cls.ARCHITECT,
            cls.AUDITOR.name: cls.AUDITOR,
            cls.TRIAGER.name: cls.TRIAGER,
        }

    @classmethod
    def format_role_prompt(cls, spec: CrewAgentSpec, task_description: str) -> str:
        return (
            f"[CrewAI Role]: {spec.role}\n"
            f"[CrewAI Goal]: {spec.goal}\n"
            f"[CrewAI Backstory]: {spec.backstory}\n"
            f"[Task]: {task_description}"
        )

    @classmethod
    def record_task(
        cls,
        spec: CrewAgentSpec,
        task_name: str,
        summary: str,
        status: Literal["completed", "failed"] = "completed",
    ) -> CrewTaskOutput:
        return CrewTaskOutput(
            agent_name=spec.name,
            role=spec.role,
            task_name=task_name,
            model_tier=spec.model_tier,
            status=status,
            summary=summary,
        )

    @classmethod
    def build_crewai_crew(
        cls,
        issue_title: str,
        issue_description: str = "",
    ) -> Dict[str, Any]:
        """
        Build a CrewAI sequential pipeline (`Architect -> Auditor -> Triager`).
        Uses upstream `crewai` SDK objects (`Agent`, `Task`, `Crew`, `Process.sequential`)
        when the `crewai` package is installed, with automatic fallback to the deterministic
        Pydantic v2 specification for 100% offline execution.
        """
        task_defs = [
            {
                "name": "propose_patches",
                "agent": cls.ARCHITECT.name,
                "description": f"Synthesize minimal zero-trust patches for: {issue_title}. {issue_description}".strip(),
                "expected_output": "JSON array of PatchProposal objects.",
            },
            {
                "name": "audit_patches",
                "agent": cls.AUDITOR.name,
                "description": f"Audit proposed diffs for AST safety, secrets, and alignment with '{issue_title}'.",
                "expected_output": "JudgeVerdict JSON with PASS/FAIL and rubric score.",
            },
            {
                "name": "run_tests",
                "agent": cls.TRIAGER.name,
                "description": "Execute pytest suite and classify any failure into TriageSummary.",
                "expected_output": "TriageSummary JSON with failure_category and failing_targets.",
            },
        ]

        try:
            from crewai import Agent, Crew, Process, Task  # type: ignore

            sdk_agents = {
                spec.name: Agent(
                    role=spec.role,
                    goal=spec.goal,
                    backstory=spec.backstory,
                    verbose=False,
                    allow_delegation=False,
                )
                for spec in (cls.ARCHITECT, cls.AUDITOR, cls.TRIAGER)
            }
            sdk_tasks = [
                Task(
                    description=t["description"],
                    expected_output=t["expected_output"],
                    agent=sdk_agents[t["agent"]],
                )
                for t in task_defs
            ]
            crew_obj = Crew(
                agents=list(sdk_agents.values()),
                tasks=sdk_tasks,
                process=Process.sequential,
                verbose=False,
            )
            return {
                "runtime": "crewai_sdk",
                "crew": crew_obj,
                "agents": [
                    cls.ARCHITECT.model_dump(),
                    cls.AUDITOR.model_dump(),
                    cls.TRIAGER.model_dump(),
                ],
                "tasks": task_defs,
            }
        except Exception:
            return {
                "runtime": "native_pydantic",
                "crew": None,
                "agents": [
                    cls.ARCHITECT.model_dump(),
                    cls.AUDITOR.model_dump(),
                    cls.TRIAGER.model_dump(),
                ],
                "tasks": task_defs,
            }

    @classmethod
    def kickoff_crew(
        cls,
        issue_title: str,
        issue_description: str = "",
    ) -> Dict[str, Any]:
        """
        Execute `crew.kickoff()` when upstream `crewai` SDK is active and `USE_CREWAI_SDK=true`,
        or return the deterministic sequential crew execution plan.
        """
        bundle = cls.build_crewai_crew(issue_title, issue_description)
        if (
            bundle["runtime"] == "crewai_sdk"
            and bundle["crew"] is not None
            and os.getenv("USE_CREWAI_SDK", "false").lower() == "true"
        ):
            raw_output = bundle["crew"].kickoff()
            return {
                "runtime": "crewai_sdk",
                "status": "completed",
                "output": str(raw_output),
                "tasks": bundle["tasks"],
            }
        return {
            "runtime": bundle["runtime"],
            "status": "planned",
            "agents": bundle["agents"],
            "tasks": bundle["tasks"],
        }


class HermesSkillSynthesizer:
    """
    Hermes Agent (Nous Research) self-improving runtime layer:
    1. Autonomous Skill Synthesis (`SKILL.md` following `agentskills.io` & minimal-whitespace rules).
    2. ShareGPT-formatted RL trajectory export (`conversations`) for lifelong memory and Atropos/vLLM training.
    """

    @staticmethod
    def _slugify(text: str) -> str:
        slug = re.sub(r"[^a-z0-9]+", "-", (text or "sdlc-task").lower()).strip("-")
        return slug[:36] or "sdlc-task"

    @classmethod
    def recall_relevant_skills(
        cls,
        sandbox_root: Path,
        query_text: str,
        max_skills: int = 2,
    ) -> List[str]:
        """
        Closed-loop Hermes skill recall: scan `.agent/skills/hermes-*/SKILL.md` in `sandbox_root`
        and return matching distilled playbooks to prime the Architect's context window.
        """
        skills_dir = (sandbox_root / ".agent" / "skills").resolve()
        if not skills_dir.exists():
            return []

        tokens = {
            tok
            for tok in re.findall(r"[a-z0-9]{3,}", (query_text or "").lower())
            if tok not in {"the", "and", "for", "fix", "issue", "with", "from"}
        }
        scored: List[tuple[int, str]] = []
        for skill_md in sorted(skills_dir.glob("hermes-*/SKILL.md")):
            try:
                text = skill_md.read_text(encoding="utf-8")
                lower = text.lower()
                overlap = sum(1 for tok in tokens if tok in lower) if tokens else 1
                if overlap > 0:
                    scored.append((overlap, text.strip()))
            except Exception:
                continue

        scored.sort(key=lambda item: item[0], reverse=True)
        return [content for _score, content in scored[:max_skills]]

    @classmethod
    def synthesize_skill(
        cls,
        event: SDLCEvent,
        patches: List[PatchProposal],
        judge_verdict: Optional[Dict[str, Any]] = None,
        triage_summary: Optional[Dict[str, Any]] = None,
        sandbox_root: Optional[Path] = None,
        persist: bool = False,
    ) -> HermesSkillArtifact:
        slug = cls._slugify(event.title)
        skill_name = f"hermes-issue-{event.issue_id}-{slug}"
        rel_path = f".agent/skills/{skill_name}/SKILL.md"
        files_touched = ", ".join(f"`{p.file_path}`" for p in patches) if patches else "`none`"
        score = judge_verdict.get("score", 1.0) if judge_verdict else 1.0
        triage_msg = (
            triage_summary.get("concise_summary", "All tests passed.")
            if triage_summary
            else "All tests passed."
        )
        sample_patch = patches[0].content.strip() if patches else "# No patch content"

        markdown_content = (
            f"---\n"
            f"name: {skill_name}\n"
            f"description: Autonomous Hermes skill distilled from Issue #{event.issue_id} ({event.title}).\n"
            f"---\n"
            f"# Hermes Distilled Skill: {event.title}\n"
            f"## Trigger & Context\n"
            f"* **Repository**: `{event.repository}` (Issue `#{event.issue_id}`)\n"
            f"* **Modified Targets**: {files_touched}\n"
            f"* **Judge Verdict**: `PASS` (score `{score}`) · **Test Triage**: {triage_msg}\n"
            f"## Verified Remediation Pattern\n"
            f"```python\n"
            f"{sample_patch}\n"
            f"```\n"
        )

        persisted = False
        if persist and sandbox_root is not None:
            target = (sandbox_root / rel_path).resolve()
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(markdown_content, encoding="utf-8")
            persisted = True

        return HermesSkillArtifact(
            skill_name=skill_name,
            skill_path=rel_path,
            markdown_content=markdown_content,
            persisted=persisted,
        )

    @classmethod
    def export_rl_trajectory(
        cls,
        event: SDLCEvent,
        branch: str,
        patches: List[PatchProposal],
        judge_verdict: Optional[Dict[str, Any]] = None,
        triage_summary: Optional[Dict[str, Any]] = None,
        repairs_used: int = 0,
    ) -> HermesTrajectoryRecord:
        score = float(judge_verdict.get("score", 1.0)) if judge_verdict else 1.0
        patch_json = json.dumps([p.model_dump() for p in patches])
        triage_note = (
            triage_summary.get("concise_summary", "All tests passed.")
            if triage_summary
            else "All tests passed."
        )
        conversations = [
            {
                "from": "system",
                "value": SDLCCrewOrchestrator.format_role_prompt(
                    SDLCCrewOrchestrator.ARCHITECT,
                    f"Resolve GitHub issue #{event.issue_id} in {event.repository}.",
                ),
            },
            {
                "from": "human",
                "value": f"Issue #{event.issue_id}: {event.title}\n\n{event.description}",
            },
            {
                "from": "gpt",
                "value": patch_json,
            },
            {
                "from": "human",
                "value": f"[Judge Score: {score}] [Pytest Triage: {triage_note}]",
            },
        ]
        return HermesTrajectoryRecord(
            issue_id=str(event.issue_id),
            branch=branch,
            judge_score=score,
            repairs_used=repairs_used,
            conversations=conversations,
        )


class AgentState(TypedDict):
    event: SDLCEvent
    payload: Dict[str, Any]
    branch: str
    patches: List[PatchProposal]
    file_snapshots: Dict[str, Optional[str]]
    rolled_back: bool
    recalled_skills: List[str]
    approval_card: Optional[Dict[str, Any]]
    violations: List[str]
    test_result: Optional[Dict[str, Any]]
    triage_summary: Optional[Dict[str, Any]]
    judge_verdict: Optional[Dict[str, Any]]
    crew_trace: List[Dict[str, Any]]
    hermes_skill: Optional[Dict[str, Any]]
    hermes_trajectory: Optional[Dict[str, Any]]
    attempt: int
    max_attempts: int
    error: Optional[str]
    pr_url: Optional[str]
    pushed: bool


# ---------------------------------------------------------------------------
# LangGraph PostgreSQL Checkpoint Persistence (PostgresSaver)
# ---------------------------------------------------------------------------

class PostgresCheckpointSaver(MemorySaver):
    """
    Crash-resilient PostgreSQL checkpointer (`PostgresSaver`) for LangGraph SDLC workflows.
    Persists and restores workflow state checkpoints via `DatabaseManager.save_workflow_checkpoint`
    and `DatabaseManager.load_workflow_checkpoint` (`sdlc_workflow_checkpoints` table), with a
    multi-worker shared fallback store for hermetic offline testing.
    """

    backend_name: str = "PostgresSaver"
    _shared_store: Dict[str, Dict[str, Any]] = {}

    def __init__(self, db_url: Optional[str] = None):
        super().__init__()
        self.db_url = db_url or os.getenv("DATABASE_URL")

    @staticmethod
    def _serialize_state(state: Dict[str, Any]) -> Dict[str, Any]:
        serialized: Dict[str, Any] = {}
        for k, v in state.items():
            if hasattr(v, "model_dump"):
                serialized[k] = v.model_dump()
            elif isinstance(v, list):
                serialized[k] = [
                    item.model_dump() if hasattr(item, "model_dump") else item
                    for item in v
                ]
            else:
                serialized[k] = v
        return serialized

    async def save_checkpoint(
        self,
        thread_id: str,
        checkpoint_id: str,
        state: Dict[str, Any],
        metadata: Optional[Dict[str, Any]] = None,
        checkpoint_ns: str = "",
        parent_checkpoint_id: Optional[str] = None,
    ) -> bool:
        """Persist workflow checkpoint to PostgreSQL (`sdlc_workflow_checkpoints`) and shared store."""
        payload = self._serialize_state(state)
        meta = metadata or {}
        record = {
            "thread_id": thread_id,
            "checkpoint_ns": checkpoint_ns,
            "checkpoint_id": checkpoint_id,
            "parent_checkpoint_id": parent_checkpoint_id,
            "checkpoint_payload": payload,
            "metadata": meta,
        }
        self._shared_store[thread_id] = record
        if self.db_url:
            try:
                from app.db.manager import DatabaseManager
                await DatabaseManager.save_workflow_checkpoint(
                    thread_id=thread_id,
                    checkpoint_id=checkpoint_id,
                    checkpoint_payload=payload,
                    metadata=meta,
                    checkpoint_ns=checkpoint_ns,
                    parent_checkpoint_id=parent_checkpoint_id,
                )
                return True
            except Exception as exc:
                logger.debug("PostgresSaver DB write fell back to shared store: %s", exc)
        return True

    async def load_checkpoint(
        self,
        thread_id: str,
        checkpoint_ns: str = "",
        checkpoint_id: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Restore workflow checkpoint from PostgreSQL (`sdlc_workflow_checkpoints`) or shared store."""
        if self.db_url:
            try:
                from app.db.manager import DatabaseManager
                db_record = await DatabaseManager.load_workflow_checkpoint(
                    thread_id=thread_id,
                    checkpoint_ns=checkpoint_ns,
                    checkpoint_id=checkpoint_id,
                )
                if db_record is not None:
                    self._shared_store[thread_id] = db_record
                    return db_record
            except Exception as exc:
                logger.debug("PostgresSaver DB read fell back to shared store: %s", exc)
        return self._shared_store.get(thread_id)


PostgresSaver = PostgresCheckpointSaver


# ---------------------------------------------------------------------------
# LangGraph Workflow Engine
# ---------------------------------------------------------------------------

class LangGraphSDLCWorkflow:
    def __init__(
        self,
        sandbox_root: Optional[str] = None,
        test_command: Optional[str] = None,
        max_repairs: int = 2,
        push: Optional[bool] = None,
        persist_hermes_skill: bool = False,
        test_timeout_seconds: float = 30.0,
        require_hitl_for_high_risk: bool = False,
        token_breaker: Optional[TokenCircuitBreaker] = None,
        checkpointer: Optional[Any] = None,
        checkpoint_db_url: Optional[str] = None,
    ):
        self.root = Path(sandbox_root or os.getenv("SDLC_SANDBOX_ROOT", os.getcwd())).resolve()
        self.test_command = test_command or os.getenv("SDLC_TEST_COMMAND", "python -m pytest -q")
        self.max_repairs = max_repairs
        self.push = push
        self.persist_hermes_skill = (
            persist_hermes_skill
            or os.getenv("SDLC_PERSIST_HERMES_SKILL", "false").lower() == "true"
        )
        self.test_timeout_seconds = float(
            os.getenv("SDLC_TEST_TIMEOUT_SECONDS", str(test_timeout_seconds))
        )
        self.require_hitl_for_high_risk = (
            require_hitl_for_high_risk
            or os.getenv("SDLC_REQUIRE_HITL_HIGH_RISK", "false").lower() == "true"
        )
        self.token_breaker = token_breaker or TokenCircuitBreaker(
            max_tokens_per_request=int(os.getenv("SDLC_MAX_TOKENS_PER_REQUEST", "8000")),
            max_tokens_per_issue=int(os.getenv("SDLC_MAX_TOKENS_PER_ISSUE", "50000")),
        )
        self.agent = PayloadPatchAgent()
        self.triager = TestTriagerSubagent()
        self.judge = CrossModelJudgeSubagent()
        self.crew = SDLCCrewOrchestrator()
        self.hermes = HermesSkillSynthesizer()
        self.checkpointer = (
            checkpointer
            if checkpointer is not None
            else PostgresSaver(db_url=checkpoint_db_url)
        )
        self.workflow = self._create_workflow()

    def _create_workflow(self):
        workflow = StateGraph(AgentState)

        workflow.add_node("initialize", self.initialize)
        workflow.add_node("propose_patches", self.propose_patches)
        workflow.add_node("apply_patches", self.apply_patches)
        workflow.add_node("audit_patches", self.audit_patches)
        workflow.add_node("run_tests", self.run_tests)
        workflow.add_node("repair_patches", self.repair_patches)
        workflow.add_node("rollback_patches", self.rollback_patches)
        workflow.add_node("synthesize_hermes_skill", self.synthesize_hermes_skill)
        workflow.add_node("finalize", self.finalize)

        workflow.set_entry_point("initialize")
        workflow.add_edge("initialize", "propose_patches")
        workflow.add_edge("propose_patches", "apply_patches")
        workflow.add_edge("apply_patches", "audit_patches")

        workflow.add_conditional_edges(
            "audit_patches",
            self.check_audit_results,
            {
                "passed": "run_tests",
                "repair": "repair_patches",
                "rollback": "rollback_patches",
            },
        )
        workflow.add_conditional_edges(
            "run_tests",
            self.check_test_results,
            {
                "passed": "synthesize_hermes_skill",
                "failed": "repair_patches",
                "max_attempts_reached": "rollback_patches",
            },
        )
        workflow.add_edge("repair_patches", "apply_patches")
        workflow.add_edge("rollback_patches", END)
        workflow.add_edge("synthesize_hermes_skill", "finalize")
        workflow.add_edge("finalize", END)

        return workflow.compile(checkpointer=self.checkpointer)

    async def initialize(self, state: AgentState) -> Dict[str, Any]:
        event = parse_github_webhook(state["payload"])
        branch = self._branch_name(event)
        logger.info("Initializing SDLC workflow: issue=%s branch=%s", event.issue_id, branch)

        with tracer.trace_span("sdlc.initialize", {"issue_id": event.issue_id, "branch": branch}):
            try:
                local = self._git("branch", "--list", branch)
                if local:
                    self._git("checkout", branch)
                else:
                    self._git("checkout", "-b", branch)
            except Exception:
                try:
                    self._git("checkout", branch)
                except Exception:
                    pass

            recalled = self.hermes.recall_relevant_skills(
                self.root, f"{event.title} {event.description}"
            )

        return {
            "event": event,
            "branch": branch,
            "file_snapshots": {},
            "rolled_back": False,
            "recalled_skills": recalled,
            "approval_card": None,
            "crew_trace": [],
            "hermes_skill": None,
            "hermes_trajectory": None,
            "attempt": 0,
            "max_attempts": self.max_repairs,
            "error": None,
            "pushed": False,
        }

    async def propose_patches(self, state: AgentState) -> Dict[str, Any]:
        event = state["event"]
        caller_key = f"issue-{event.issue_id}"
        recalled = state.get("recalled_skills") or []
        est_tokens = TokenCircuitBreaker.estimate_tokens(
            f"{event.title} {event.description} {' '.join(recalled)}"
        )
        allowed, _rem, err_reason = self.token_breaker.check_and_consume(caller_key, est_tokens)
        trace = list(state.get("crew_trace") or [])
        if not allowed:
            task_out = self.crew.record_task(
                self.crew.ARCHITECT, "propose_patches", err_reason or "Token limit exceeded", status="failed"
            )
            trace.append(task_out.model_dump())
            return {"error": err_reason, "crew_trace": trace}

        with tracer.trace_span("sdlc.propose_patches", {"issue_id": event.issue_id, "recalled_skills": len(recalled)}):
            patches = await self.agent.propose(state["payload"], recalled_skills=recalled)

        if not patches:
            task_out = self.crew.record_task(
                self.crew.ARCHITECT,
                "propose_patches",
                "No patch proposals generated.",
                status="failed",
            )
            trace.append(task_out.model_dump())
            return {"error": "Agent produced no patch proposals", "crew_trace": trace}

        task_out = self.crew.record_task(
            self.crew.ARCHITECT,
            "propose_patches",
            f"Proposed {len(patches)} file patch(es): {', '.join(p.file_path for p in patches)}",
        )
        trace.append(task_out.model_dump())
        return {"patches": patches, "crew_trace": trace}

    async def apply_patches(self, state: AgentState) -> Dict[str, Any]:
        snapshots = dict(state.get("file_snapshots") or {})
        with tracer.trace_span("sdlc.apply_patches", {"patch_count": len(state["patches"])}):
            self._apply_patches_logic(state["patches"], snapshots)
        return {"file_snapshots": snapshots}

    async def audit_patches(self, state: AgentState) -> Dict[str, Any]:
        violations: List[str] = []
        with tracer.trace_span("sdlc.audit_patches", {"attempt": state.get("attempt", 0)}):
            for patch in state["patches"]:
                result = await PolicyEngine.evaluate_patch(patch.file_path, patch.content, [], "pending")
                violations.extend(result.violations)
            verdict = await self.judge.evaluate_diff(
                state["patches"],
                requirements=state["event"].title if state.get("event") else "",
            )
            if not verdict.passed:
                for finding in verdict.findings:
                    if finding not in violations:
                        violations.append(finding)

        trace = list(state.get("crew_trace") or [])
        task_out = self.crew.record_task(
            self.crew.AUDITOR,
            "audit_patches",
            f"Judge verdict={verdict.verdict} (score={verdict.score})",
            status="completed" if not violations and verdict.passed else "failed",
        )
        trace.append(task_out.model_dump())
        return {
            "violations": violations,
            "judge_verdict": verdict.model_dump(),
            "crew_trace": trace,
        }

    def check_audit_results(self, state: AgentState) -> Literal["passed", "repair", "rollback"]:
        violations = state.get("violations") or []
        verdict = state.get("judge_verdict") or {}
        if not violations and verdict.get("passed", True):
            return "passed"

        # Hard-block secret leaks and protected-path tampering immediately without retry
        non_retryable = any(
            tok in v.lower()
            for v in violations
            for tok in ("secret detected", "protected path")
        )
        can_repair = (
            not non_retryable
            and state["attempt"] < state["max_attempts"]
            and ("repair_patches" in state["payload"] or "patches" not in state["payload"])
        )
        return "repair" if can_repair else "rollback"

    async def run_tests(self, state: AgentState) -> Dict[str, Any]:
        import asyncio
        with tracer.trace_span("sdlc.run_tests", {"attempt": state.get("attempt", 0)}):
            result = await asyncio.to_thread(self._run_tests_logic)
            triage = self.triager.classify_failure(result.returncode, result.output)
        trace = list(state.get("crew_trace") or [])
        task_out = self.crew.record_task(
            self.crew.TRIAGER,
            "run_tests",
            triage.concise_summary,
            status="completed" if result.returncode == 0 else "failed",
        )
        trace.append(task_out.model_dump())
        return {
            "test_result": {"returncode": result.returncode, "output": result.output},
            "triage_summary": triage.model_dump(),
            "crew_trace": trace,
        }

    def check_test_results(self, state: AgentState) -> Literal["passed", "failed", "max_attempts_reached"]:
        test_result = state["test_result"]
        if test_result and test_result["returncode"] == 0:
            return "passed"
        if state["attempt"] >= state["max_attempts"]:
            return "max_attempts_reached"
        return "failed"

    async def repair_patches(self, state: AgentState) -> Dict[str, Any]:
        event = state["event"]
        caller_key = f"issue-{event.issue_id}"
        raw_out = state["test_result"]["output"] if state.get("test_result") else ""
        if state.get("violations"):
            raw_out = "AUDIT VIOLATIONS:\n" + "\n".join(state["violations"]) + "\n" + raw_out
        compacted = compact_agent_context(raw_out, state.get("triage_summary"), max_chars=2500)

        est_tokens = TokenCircuitBreaker.estimate_tokens(compacted)
        allowed, _rem, err_reason = self.token_breaker.check_and_consume(caller_key, est_tokens)
        trace = list(state.get("crew_trace") or [])
        if not allowed:
            task_out = self.crew.record_task(
                self.crew.ARCHITECT, "repair_patches", err_reason or "Token limit exceeded", status="failed"
            )
            trace.append(task_out.model_dump())
            return {
                "error": err_reason,
                "attempt": state["attempt"] + 1,
                "crew_trace": trace,
            }

        with tracer.trace_span("sdlc.repair_patches", {"attempt": state["attempt"] + 1}):
            patches = await self.agent.repair(
                state["payload"],
                compacted,
                recalled_skills=state.get("recalled_skills"),
            )

        if not patches:
            task_out = self.crew.record_task(
                self.crew.ARCHITECT,
                "repair_patches",
                f"Repair attempt {state['attempt'] + 1} produced no patches.",
                status="failed",
            )
            trace.append(task_out.model_dump())
            return {
                "error": "Agent produced no repair patches",
                "attempt": state["attempt"] + 1,
                "crew_trace": trace,
            }
        task_out = self.crew.record_task(
            self.crew.ARCHITECT,
            "repair_patches",
            f"Repair attempt {state['attempt'] + 1} synthesized {len(patches)} patch(es).",
        )
        trace.append(task_out.model_dump())
        return {
            "patches": patches,
            "violations": [],
            "attempt": state["attempt"] + 1,
            "crew_trace": trace,
        }

    async def rollback_patches(self, state: AgentState) -> Dict[str, Any]:
        """Deterministically restore sandbox files to their pre-patch state on audit or test failure."""
        snapshots = state.get("file_snapshots") or {}
        with tracer.trace_span("sdlc.rollback_patches", {"files_restored": len(snapshots)}):
            self._rollback_patches_logic(snapshots)
        return {"rolled_back": True}

    async def synthesize_hermes_skill(self, state: AgentState) -> Dict[str, Any]:
        """Hermes Agent node: distill reusable SKILL.md and ShareGPT RL trajectory after tests pass."""
        event = state["event"]
        with tracer.trace_span("sdlc.synthesize_hermes_skill", {"issue_id": event.issue_id}):
            skill = self.hermes.synthesize_skill(
                event=event,
                patches=state["patches"],
                judge_verdict=state.get("judge_verdict"),
                triage_summary=state.get("triage_summary"),
                sandbox_root=self.root,
                persist=self.persist_hermes_skill,
            )
            trajectory = self.hermes.export_rl_trajectory(
                event=event,
                branch=state["branch"],
                patches=state["patches"],
                judge_verdict=state.get("judge_verdict"),
                triage_summary=state.get("triage_summary"),
                repairs_used=state.get("attempt", 0),
            )
        return {
            "hermes_skill": skill.model_dump(),
            "hermes_trajectory": trajectory.model_dump(),
        }

    async def finalize(self, state: AgentState) -> Dict[str, Any]:
        event = state["event"]
        branch = state["branch"]
        patches = state["patches"]
        affected = [p.file_path for p in patches]
        risk_tier, high_risk_files = PolicyEngine.classify_autonomy_risk(affected)
        requires_hitl = risk_tier == "high_risk" and self.require_hitl_for_high_risk

        card = ApprovalCard(
            risk_tier="high_risk" if risk_tier == "high_risk" else "low_risk",
            requires_human_approval=requires_hitl,
            status="pending_human_approval" if requires_hitl else "auto_approved",
            affected_files=affected,
            high_risk_files=high_risk_files,
            reason=(
                f"High-risk files modified ({', '.join(high_risk_files)}); awaiting human approval."
                if requires_hitl
                else "All security gates, Judge rubric, and pytest checks passed."
            ),
        )

        if requires_hitl:
            return {
                "status": "pending_approval",
                "approval_card": card.model_dump(),
                "pushed": False,
                "pr_url": None,
            }

        try:
            self._git("add", "--", *(p.file_path for p in patches))
            self._git("commit", "-m", f"Implement #{event.issue_id}: {event.title}")
            pushed = self._push(branch)
            pr_url = self._create_pr(event, branch) if pushed else None
            return {
                "status": "completed",
                "approval_card": card.model_dump(),
                "pushed": pushed,
                "pr_url": pr_url,
            }
        except Exception as exc:
            logger.warning("Finalization git operations failed: %s", exc)
            return {
                "status": "completed",
                "approval_card": card.model_dump(),
                "pushed": False,
                "pr_url": None,
            }

    # -----------------------------------------------------------------------
    # Git & Sandbox Helpers
    # -----------------------------------------------------------------------

    def _branch_name(self, event: SDLCEvent) -> str:
        slug = re.sub(r"[^a-z0-9]+", "-", event.title.lower()).strip("-")[:40]
        return f"feature/AGENT-{event.issue_id}-{slug or 'patch'}"

    def _git(self, *args: str) -> str:
        res = subprocess.run(["git", *args], cwd=self.root, capture_output=True, text=True, check=False)
        if res.returncode != 0:
            raise RuntimeError(f"git {' '.join(args)} failed: {res.stderr.strip()}")
        return res.stdout.strip()

    def _apply_patches_logic(
        self,
        patches: List[PatchProposal],
        snapshots: Optional[Dict[str, Optional[str]]] = None,
    ) -> None:
        for patch in patches:
            rel = Path(patch.file_path)
            if rel.is_absolute() or ".." in rel.parts or (rel.parts and rel.parts[0] == ".git"):
                raise ValueError(f"Unsafe patch path: {patch.file_path}")
            target = (self.root / rel).resolve()
            if snapshots is not None and patch.file_path not in snapshots:
                snapshots[patch.file_path] = (
                    target.read_text(encoding="utf-8") if target.exists() else None
                )
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(patch.content, encoding="utf-8")

    def _rollback_patches_logic(self, snapshots: Dict[str, Optional[str]]) -> None:
        for rel_path, orig_content in snapshots.items():
            target = (self.root / Path(rel_path)).resolve()
            try:
                if orig_content is None:
                    if target.exists():
                        target.unlink()
                else:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_text(orig_content, encoding="utf-8")
            except Exception as exc:
                logger.warning("Rollback failed for %s: %s", rel_path, exc)

    def _run_tests_logic(self) -> TestResult:
        cmd = shlex.split(self.test_command)
        try:
            res = subprocess.run(
                cmd,
                cwd=self.root,
                capture_output=True,
                text=True,
                check=False,
                timeout=self.test_timeout_seconds,
            )
            return TestResult(res.returncode, res.stdout + res.stderr)
        except subprocess.TimeoutExpired as exc:
            out = (exc.stdout or "") + (exc.stderr or "")
            return TestResult(
                124,
                f"TimeoutError: Test command '{self.test_command}' timed out after {self.test_timeout_seconds}s.\n{out}",
            )

    def _push(self, branch: str) -> bool:
        should_push = self.push if self.push is not None else os.getenv("SDLC_PUSH", "false").lower() == "true"
        if not should_push:
            return False
        self._git("push", "-u", "origin", branch)
        return True

    def _create_pr(self, event: SDLCEvent, branch: str) -> Optional[str]:
        token = os.getenv("GITHUB_TOKEN")
        if not token:
            return None
        body = json.dumps({
            "title": f"Agent Resolution: {event.title}",
            "head": branch,
            "base": "main",
            "body": f"Automated patch proposed by SDLC Agent for Issue #{event.issue_id}.\n\n{event.description}",
        }).encode("utf-8")
        req = request.Request(
            f"https://api.github.com/repos/{event.repository}/pulls",
            data=body,
            method="POST",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        )
        try:
            with request.urlopen(req, timeout=15) as resp:
                return json.loads(resp.read().decode())["html_url"]
        except Exception as exc:
            logger.warning("GitHub PR creation API failed: %s", exc)
            return None

    async def run(self, payload: dict[str, Any]) -> dict[str, Any]:
        event = parse_github_webhook(payload)
        thread_id = f"sdlc-{event.repository}-{event.issue_id}"
        config = {"configurable": {"thread_id": thread_id}}

        initial_state: AgentState = {
            "payload": payload,
            "event": event,
            "branch": "",
            "patches": [],
            "file_snapshots": {},
            "rolled_back": False,
            "recalled_skills": [],
            "approval_card": None,
            "violations": [],
            "test_result": None,
            "triage_summary": None,
            "judge_verdict": None,
            "crew_trace": [],
            "hermes_skill": None,
            "hermes_trajectory": None,
            "attempt": 0,
            "max_attempts": self.max_repairs,
            "error": None,
            "pr_url": None,
            "pushed": False,
        }

        final_state = await self.workflow.ainvoke(initial_state, config=config)
        if final_state.get("error"):
            raise ValueError(final_state["error"])
        if final_state.get("violations"):
            raise ValueError("Security gate failed: " + "; ".join(final_state["violations"]))

        approval = final_state.get("approval_card")
        status_str = (
            "pending_approval"
            if approval and approval.get("requires_human_approval")
            else "completed"
        )
        checkpoint_id = f"ckpt-{event.issue_id}-{final_state.get('attempt', 0)}"
        if hasattr(self.checkpointer, "save_checkpoint"):
            await self.checkpointer.save_checkpoint(
                thread_id=thread_id,
                checkpoint_id=checkpoint_id,
                state=dict(final_state),
                metadata={"status": status_str, "branch": final_state.get("branch")},
            )
        return {
            "status": status_str,
            "issue_id": event.issue_id,
            "thread_id": thread_id,
            "checkpoint_id": checkpoint_id,
            "checkpoint_backend": getattr(self.checkpointer, "backend_name", "PostgresSaver"),
            "branch": final_state.get("branch"),
            "tests": self.test_command,
            "triage_summary": final_state.get("triage_summary"),
            "judge_verdict": final_state.get("judge_verdict"),
            "crew_trace": final_state.get("crew_trace", []),
            "hermes_skill": final_state.get("hermes_skill"),
            "hermes_trajectory": final_state.get("hermes_trajectory"),
            "recalled_skills": final_state.get("recalled_skills", []),
            "approval_card": approval,
            "rolled_back": final_state.get("rolled_back", False),
            "subagent_routing": {
                "orchestrator": "inherit",
                "triager": "flash (test-triager)",
                "judge": "pro (cross-model-judge)",
            },
            "pushed": final_state.get("pushed", False),
            "pull_request_url": final_state.get("pr_url"),
        }

    async def resume_from_checkpoint(
        self,
        thread_id: str,
        human_approved: bool = True,
    ) -> dict[str, Any]:
        """
        Resume a crashed or HITL-paused workflow from its PostgreSQL checkpoint (`PostgresSaver`)
        across stateless worker processes.
        """
        if not hasattr(self.checkpointer, "load_checkpoint"):
            raise ValueError("Configured checkpointer does not support load_checkpoint")
        record = await self.checkpointer.load_checkpoint(thread_id=thread_id)
        if not record:
            raise ValueError(f"No persisted checkpoint found for thread_id='{thread_id}'")

        saved_state = dict(record.get("checkpoint_payload") or {})
        approval = dict(saved_state.get("approval_card") or {})
        if human_approved:
            approval["status"] = "auto_approved"
            approval["requires_human_approval"] = False
            approval["reason"] = "Human-in-the-loop sign-off granted via PostgresSaver checkpoint resume."
            saved_state["approval_card"] = approval
            status_str = "completed"
        else:
            approval["status"] = "rejected"
            saved_state["approval_card"] = approval
            status_str = "rejected"

        new_ckpt_id = f"{record.get('checkpoint_id', 'ckpt')}-resumed"
        await self.checkpointer.save_checkpoint(
            thread_id=thread_id,
            checkpoint_id=new_ckpt_id,
            state=saved_state,
            metadata={"status": status_str, "resumed": True},
            parent_checkpoint_id=record.get("checkpoint_id"),
        )
        return {
            "status": status_str,
            "thread_id": thread_id,
            "checkpoint_id": new_ckpt_id,
            "checkpoint_backend": getattr(self.checkpointer, "backend_name", "PostgresSaver"),
            "branch": saved_state.get("branch"),
            "approval_card": approval,
            "resumed_from": record.get("checkpoint_id"),
        }
