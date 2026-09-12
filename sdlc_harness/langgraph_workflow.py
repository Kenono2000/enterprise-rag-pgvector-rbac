import operator
from typing import Annotated, Any, Dict, List, Optional, TypedDict, Union, Literal

from langchain_openai import ChatOpenAI
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver
from pydantic import BaseModel, Field

from .agents.patch_agent import PatchProposal, PayloadPatchAgent
from .policies.guardrails import PolicyEngine
from .webhooks.parser import SDLCEvent, parse_github_webhook
import os
import subprocess
from pathlib import Path
import asyncio

class AgentState(TypedDict):
    event: SDLCEvent
    payload: Dict[str, Any]
    branch: str
    patches: List[PatchProposal]
    violations: List[str]
    test_result: Optional[Dict[str, Any]]
    attempt: int
    max_attempts: int
    error: Optional[str]
    pr_url: Optional[str]
    pushed: bool

class LangGraphSDLCWorkflow:
    def __init__(
        self,
        sandbox_root: Optional[str] = None,
        test_command: Optional[str] = None,
        max_repairs: int = 2,
        push: Optional[bool] = None,
    ):
        self.root = Path(
            sandbox_root or os.getenv("SDLC_SANDBOX_ROOT", os.getcwd())
        ).resolve()
        self.test_command = test_command or os.getenv(
            "SDLC_TEST_COMMAND", "python -m pytest -q"
        )
        self.max_repairs = max_repairs
        self.push = push
        self.agent = PayloadPatchAgent()
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
            {
                "failed": END,
                "passed": "run_tests"
            }
        )

        workflow.add_conditional_edges(
            "run_tests",
            self.check_test_results,
            {
                "passed": "finalize",
                "failed": "repair_patches",
                "max_attempts_reached": END
            }
        )

        workflow.add_edge("repair_patches", "apply_patches")
        workflow.add_edge("finalize", END)

        return workflow.compile(checkpointer=self.checkpointer)

    async def initialize(self, state: AgentState) -> Dict[str, Any]:
        event = parse_github_webhook(state["payload"])
        branch = self._branch_name(event)
        self._git("checkout", "-b", branch)
        return {
            "event": event,
            "branch": branch,
            "attempt": 0,
            "max_attempts": self.max_repairs,
            "error": None,
            "pushed": False
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
            result = await PolicyEngine.evaluate_patch(
                patch.file_path, patch.content, [], "pending"
            )
            violations.extend(result.violations)
        return {"violations": violations}

    def check_audit_results(self, state: AgentState) -> Literal["failed", "passed"]:
        if state["violations"]:
            return "failed"
        return "passed"

    async def run_tests(self, state: AgentState) -> Dict[str, Any]:
        result = await asyncio.to_thread(self._run_tests_logic)
        return {"test_result": {"returncode": result.returncode, "output": result.output}}

    def check_test_results(self, state: AgentState) -> Literal["passed", "failed", "max_attempts_reached"]:
        test_result = state["test_result"]
        if test_result["returncode"] == 0:
            return "passed"
        
        if state["attempt"] >= state["max_attempts"]:
            return "max_attempts_reached"
        
        return "failed"

    async def repair_patches(self, state: AgentState) -> Dict[str, Any]:
        test_output = state["test_result"]["output"][-6000:]
        patches = await self.agent.repair(state["payload"], test_output)
        if not patches:
            return {"error": "Agent produced no repair patches", "attempt": state["attempt"] + 1}
        return {"patches": patches, "attempt": state["attempt"] + 1}

    async def finalize(self, state: AgentState) -> Dict[str, Any]:
        event = state["event"]
        branch = state["branch"]
        patches = state["patches"]
        
        self._git("add", "--", *(patch.file_path for patch in patches))
        self._git("commit", "-m", f"Implement {event.title}")
        pushed = self._push(branch)
        pr_url = self._create_pr(event, branch) if pushed else None
        
        return {
            "status": "completed",
            "pushed": pushed,
            "pr_url": pr_url
        }

    # Helper methods (copied and adapted from SDLCWorkflow)
    def _branch_name(self, event: SDLCEvent) -> str:
        import re
        slug = re.sub(r"[^a-z0-9]+", "-", event.title.lower()).strip("-")[:50]
        return f"feature/AGENT-{event.issue_id}-{slug or 'change'}"

    def _git(self, *args: str) -> str:
        result = subprocess.run(
            ["git", *args], cwd=self.root, capture_output=True, text=True, check=False
        )
        if result.returncode:
            raise RuntimeError(f"git {' '.join(args)} failed: {result.stderr.strip()}")
        return result.stdout.strip()

    def _apply_patches_logic(self, patches: list[PatchProposal]) -> None:
        max_size = int(os.getenv("SDLC_MAX_PATCH_SIZE", "1048576"))  # Default 1MB
        for patch in patches:
            if len(patch.content) > max_size:
                raise ValueError(f"Patch content exceeds size limit: {len(patch.content)} bytes")
            relative = Path(patch.file_path)
            if (
                relative.is_absolute()
                or ".." in relative.parts
                or (relative.parts and relative.parts[0] == ".git")
            ):
                raise ValueError(f"Unsafe patch path: {patch.file_path}")
            target = (self.root / relative).resolve()
            if target != self.root and self.root not in target.parents:
                raise ValueError(f"Patch escapes sandbox: {patch.file_path}")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(patch.content, encoding="utf-8")

    def _run_tests_logic(self) -> Any:
        from .lifecycle import TestResult
        import shlex
        
        cmd = shlex.split(self.test_command)
        result = subprocess.run(
            cmd,
            cwd=self.root,
            shell=False,
            capture_output=True,
            text=True,
            check=False,
        )
        return TestResult(result.returncode, result.stdout + result.stderr)

    def _push(self, branch: str) -> bool:
        should_push = self.push
        if should_push is None:
            should_push = os.getenv("SDLC_PUSH", "false").lower() == "true"
        if not should_push:
            return False
        self._git("push", "-u", "origin", branch)
        return True

    def _create_pr(self, event: SDLCEvent, branch: str) -> Optional[str]:
        from urllib import request
        import json
        token = os.getenv("GITHUB_TOKEN")
        if not token:
            return None
        body = json.dumps(
            {
                "title": event.title,
                "head": branch,
                "base": os.getenv("GITHUB_BASE_BRANCH", "main"),
                "body": event.description,
            }
        ).encode()
        url = f"https://api.github.com/repos/{event.repository}/pulls"
        
        # Check for existing PR to maintain idempotency
        check_req = request.Request(
            f"{url}?head={event.repository.split('/')[0]}:{branch}&state=open",
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {token}",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
        try:
            with request.urlopen(check_req, timeout=20) as response:
                existing_prs = json.loads(response.read().decode())
                if existing_prs:
                    return existing_prs[0]["html_url"]
        except Exception:
            pass

        req = request.Request(
            url,
            data=body,
            method="POST",
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {token}",
                "X-GitHub-Api-Version": "2022-11-28",
                "Content-Type": "application/json",
            },
        )
        try:
            with request.urlopen(req, timeout=20) as response:
                return json.loads(response.read().decode())["html_url"]
        except Exception:
            return None

    async def run(self, payload: dict[str, Any]) -> dict[str, Any]:
        event = parse_github_webhook(payload)
        thread_id = f"sdlc-{event.repository}-{event.issue_id}"
        config = {"configurable": {"thread_id": thread_id}}
        
        initial_state: AgentState = {
            "payload": payload,
            "event": None, # type: ignore
            "branch": "",
            "patches": [],
            "violations": [],
            "test_result": None,
            "attempt": 0,
            "max_attempts": self.max_repairs,
            "error": None,
            "pr_url": None,
            "pushed": False
        }
        
        final_state = await self.workflow.ainvoke(initial_state, config=config)
        
        if final_state.get("error"):
            raise ValueError(final_state["error"])
        
        if final_state.get("violations"):
            raise ValueError("Security gate failed: " + "; ".join(final_state["violations"]))

        if final_state.get("test_result") and final_state["test_result"]["returncode"] != 0:
             raise RuntimeError(
                    f"Tests failed after {self.max_repairs} repair attempts: "
                    f"{final_state['test_result']['output'][-2000:]}"
                )

        return {
            "status": "completed",
            "issue_id": final_state["event"].issue_id,
            "branch": final_state["branch"],
            "tests": self.test_command,
            "pushed": final_state["pushed"],
            "pull_request_url": final_state["pr_url"],
            "pull_request_created": final_state["pr_url"] is not None,
        }
