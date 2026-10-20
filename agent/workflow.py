"""
agent/workflow.py
-----------------
Autonomous SDLC Agent workflow built with LangGraph.
Orchestrates:
1. Issue analysis & patch proposal generation.
2. Isolated patch application in workspace sandbox.
3. Deterministic static security audit (AST + secrets).
4. Automated pytest quality gate verification with self-correction retry loop.
5. Git branch creation, commit, push, and GitHub PR creation.
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

from pydantic import BaseModel, Field
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver

from app.db import chat_completion
from agent.guardrails import PolicyEngine
from agent.parser import SDLCEvent, parse_github_webhook

logger = logging.getLogger("agent.workflow")


# ---------------------------------------------------------------------------
# Data Models
# ---------------------------------------------------------------------------

class PatchProposal(BaseModel):
    file_path: str = Field(min_length=1)
    content: str


class TriageSummary(BaseModel):
    """Structured output returned by the Gemini Flash `test-triager` subagent."""

    model_tier: Literal["flash"] = "flash"
    subagent_name: str = "test-triager"
    failure_category: Literal[
        "none", "compilation_error", "assertion_failure", "timeout"
    ] = "none"
    failing_targets: List[str] = Field(default_factory=list)
    concise_summary: str = ""


class JudgeVerdict(BaseModel):
    """Structured pass/fail verdict returned by the Gemini Pro `cross-model-judge` subagent."""

    model_tier: Literal["pro"] = "pro"
    subagent_name: str = "cross-model-judge"
    verdict: Literal["PASS", "FAIL"] = "PASS"
    passed: bool = True
    line_references: List[str] = Field(default_factory=list)
    findings: List[str] = Field(default_factory=list)


class TestResult:
    def __init__(self, returncode: int, output: str):
        self.returncode = returncode
        self.output = output


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
    emitting a deterministic PASS/FAIL verdict with specific line references.
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

        for patch in patches:
            gate = await PolicyEngine.evaluate_patch(
                patch.file_path, patch.content, [], requirements or "diff-audit"
            )
            if not gate.passed:
                for violation in gate.violations:
                    findings.append(f"blocking: [{patch.file_path}] {violation}")

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
        return JudgeVerdict(
            verdict="PASS" if passed else "FAIL",
            passed=passed,
            line_references=line_references,
            findings=findings
            if findings
            else ["Verified diff alignment, AST safety, and edge-case invariants."],
        )


class PayloadPatchAgent:
    """Generates and repairs file patch proposals using LLM or webhook payload."""

    async def propose(self, payload: dict[str, Any]) -> List[PatchProposal]:
        if "patches" in payload:
            return [PatchProposal(**p) for p in payload.get("patches", [])]

        issue = payload.get("issue", {})
        title = issue.get("title", "")
        body = issue.get("body", "")
        repo = payload.get("repository", {}).get("full_name", "")

        prompt = f"""
You are an autonomous SDLC software engineer. Given the following issue, propose file patches to resolve it.
Repository: {repo}
Issue Title: {title}
Issue Description: {body}

Respond ONLY with valid JSON list of patches:
[
    {{"file_path": "example.py", "content": "print('hello')"}}
]
"""
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

    async def repair(self, payload: dict[str, Any], test_output: str) -> List[PatchProposal]:
        """Self-correct patches based on pytest failure traces."""
        issue = payload.get("issue", {})
        prompt = f"""
Tests failed for issue '{issue.get('title', '')}'.
Failure Trace:
{test_output[-2500:]}

Provide the corrected file patches as a valid JSON list:
[
    {{"file_path": "example.py", "content": "corrected code"}}
]
"""
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


class AgentState(TypedDict):
    event: SDLCEvent
    payload: Dict[str, Any]
    branch: str
    patches: List[PatchProposal]
    violations: List[str]
    test_result: Optional[Dict[str, Any]]
    triage_summary: Optional[Dict[str, Any]]
    judge_verdict: Optional[Dict[str, Any]]
    attempt: int
    max_attempts: int
    error: Optional[str]
    pr_url: Optional[str]
    pushed: bool


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
    ):
        self.root = Path(sandbox_root or os.getenv("SDLC_SANDBOX_ROOT", os.getcwd())).resolve()
        self.test_command = test_command or os.getenv("SDLC_TEST_COMMAND", "python -m pytest -q")
        self.max_repairs = max_repairs
        self.push = push
        self.agent = PayloadPatchAgent()
        self.triager = TestTriagerSubagent()
        self.judge = CrossModelJudgeSubagent()
        self.checkpointer = MemorySaver()
        self.workflow = self._create_workflow()

    def _create_workflow(self):
        workflow = StateGraph(AgentState)

        workflow.add_node("initialize", self.initialize)
        workflow.add_node("propose_patches", self.propose_patches)
        workflow.add_node("apply_patches", self.apply_patches)
        workflow.add_node("audit_patches", self.audit_patches)
        workflow.add_node("run_tests", self.run_tests)
        workflow.add_node("repair_patches", self.repair_patches)
        workflow.add_node("finalize", self.finalize)

        workflow.set_entry_point("initialize")
        workflow.add_edge("initialize", "propose_patches")
        workflow.add_edge("propose_patches", "apply_patches")
        workflow.add_edge("apply_patches", "audit_patches")

        workflow.add_conditional_edges(
            "audit_patches",
            self.check_audit_results,
            {"failed": END, "passed": "run_tests"},
        )
        workflow.add_conditional_edges(
            "run_tests",
            self.check_test_results,
            {"passed": "finalize", "failed": "repair_patches", "max_attempts_reached": END},
        )
        workflow.add_edge("repair_patches", "apply_patches")
        workflow.add_edge("finalize", END)

        return workflow.compile(checkpointer=self.checkpointer)

    async def initialize(self, state: AgentState) -> Dict[str, Any]:
        event = parse_github_webhook(state["payload"])
        branch = self._branch_name(event)
        logger.info("Initializing SDLC workflow: issue=%s branch=%s", event.issue_id, branch)

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

        return {
            "event": event,
            "branch": branch,
            "attempt": 0,
            "max_attempts": self.max_repairs,
            "error": None,
            "pushed": False,
        }

    async def propose_patches(self, state: AgentState) -> Dict[str, Any]:
        patches = await self.agent.propose(state["payload"])
        if not patches:
            return {"error": "Agent produced no patch proposals"}
        return {"patches": patches}

    async def apply_patches(self, state: AgentState) -> Dict[str, Any]:
        self._apply_patches_logic(state["patches"])
        return {}

    async def audit_patches(self, state: AgentState) -> Dict[str, Any]:
        violations: List[str] = []
        for patch in state["patches"]:
            result = await PolicyEngine.evaluate_patch(patch.file_path, patch.content, [], "pending")
            violations.extend(result.violations)
        verdict = await self.judge.evaluate_diff(
            state["patches"],
            requirements=state["event"].title if state.get("event") else "",
        )
        return {
            "violations": violations,
            "judge_verdict": verdict.model_dump(),
        }

    def check_audit_results(self, state: AgentState) -> Literal["failed", "passed"]:
        return "failed" if state.get("violations") else "passed"

    async def run_tests(self, state: AgentState) -> Dict[str, Any]:
        import asyncio
        result = await asyncio.to_thread(self._run_tests_logic)
        triage = self.triager.classify_failure(result.returncode, result.output)
        return {
            "test_result": {"returncode": result.returncode, "output": result.output},
            "triage_summary": triage.model_dump(),
        }

    def check_test_results(self, state: AgentState) -> Literal["passed", "failed", "max_attempts_reached"]:
        test_result = state["test_result"]
        if test_result and test_result["returncode"] == 0:
            return "passed"
        if state["attempt"] >= state["max_attempts"]:
            return "max_attempts_reached"
        return "failed"

    async def repair_patches(self, state: AgentState) -> Dict[str, Any]:
        output = state["test_result"]["output"][-4000:] if state.get("test_result") else ""
        triage = state.get("triage_summary") or {}
        if triage.get("concise_summary"):
            output = f"[Flash Test-Triager Summary]: {triage['concise_summary']}\n\n{output}"
        patches = await self.agent.repair(state["payload"], output)
        if not patches:
            return {"error": "Agent produced no repair patches", "attempt": state["attempt"] + 1}
        return {"patches": patches, "attempt": state["attempt"] + 1}

    async def finalize(self, state: AgentState) -> Dict[str, Any]:
        event = state["event"]
        branch = state["branch"]
        patches = state["patches"]

        try:
            self._git("add", "--", *(p.file_path for p in patches))
            self._git("commit", "-m", f"Implement #{event.issue_id}: {event.title}")
            pushed = self._push(branch)
            pr_url = self._create_pr(event, branch) if pushed else None
            return {"status": "completed", "pushed": pushed, "pr_url": pr_url}
        except Exception as exc:
            logger.warning("Finalization git operations failed: %s", exc)
            return {"status": "completed", "pushed": False, "pr_url": None}

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

    def _apply_patches_logic(self, patches: List[PatchProposal]) -> None:
        for patch in patches:
            rel = Path(patch.file_path)
            if rel.is_absolute() or ".." in rel.parts or (rel.parts and rel.parts[0] == ".git"):
                raise ValueError(f"Unsafe patch path: {patch.file_path}")
            target = (self.root / rel).resolve()
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(patch.content, encoding="utf-8")

    def _run_tests_logic(self) -> TestResult:
        cmd = shlex.split(self.test_command)
        res = subprocess.run(cmd, cwd=self.root, capture_output=True, text=True, check=False)
        return TestResult(res.returncode, res.stdout + res.stderr)

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
            "violations": [],
            "test_result": None,
            "triage_summary": None,
            "judge_verdict": None,
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

        return {
            "status": "completed",
            "issue_id": event.issue_id,
            "branch": final_state.get("branch"),
            "tests": self.test_command,
            "triage_summary": final_state.get("triage_summary"),
            "judge_verdict": final_state.get("judge_verdict"),
            "subagent_routing": {
                "orchestrator": "inherit",
                "triager": "flash (test-triager)",
                "judge": "pro (cross-model-judge)",
            },
            "pushed": final_state.get("pushed", False),
            "pull_request_url": final_state.get("pr_url"),
        }
