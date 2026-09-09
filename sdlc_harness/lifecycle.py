import asyncio
import hashlib
import hmac
import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any, Optional
from urllib import request

from dotenv import load_dotenv

from .agents.patch_agent import PatchAgent, PatchProposal, PayloadPatchAgent
from .policies.guardrails import PolicyEngine
from .webhooks.parser import SDLCEvent, parse_github_webhook

load_dotenv()


class SDLCWorkflow:
    def __init__(
        self,
        sandbox_root: Optional[str] = None,
        agent: Optional[PatchAgent] = None,
        test_command: Optional[str] = None,
        max_repairs: int = 2,
        push: Optional[bool] = None,
    ):
        self.root = Path(
            sandbox_root or os.getenv("SDLC_SANDBOX_ROOT", os.getcwd())
        ).resolve()
        self.agent = agent or PayloadPatchAgent()
        self.test_command = test_command or os.getenv(
            "SDLC_TEST_COMMAND", "python -m pytest -q"
        )
        self.max_repairs = max_repairs
        self.push = push

    async def run(self, payload: dict[str, Any]) -> dict[str, Any]:
        event = parse_github_webhook(payload)
        branch = self._branch_name(event)
        self._git("checkout", "-b", branch)

        patches = await self.agent.propose(payload)
        if not patches:
            raise ValueError("Agent produced no patch proposals")

        for attempt in range(self.max_repairs + 1):
            self._apply_patches(patches)
            violations = await self._audit(patches)
            if violations:
                raise ValueError("Security gate failed: " + "; ".join(violations))

            test_result = await asyncio.to_thread(self._run_tests)
            if test_result.returncode == 0:
                break
            if attempt == self.max_repairs:
                raise RuntimeError(
                    f"Tests failed after {self.max_repairs} repair attempts: "
                    f"{test_result.output[-2000:]}"
                )
            patches = await self.agent.repair(payload, test_result.output[-6000:])
            if not patches:
                raise RuntimeError("Agent produced no repair patches")
        else:
            raise RuntimeError("SDLC workflow exhausted without a test result")

        self._git("add", "--", *(patch.file_path for patch in patches))
        self._git("commit", "-m", f"Implement {event.title}")
        pushed = self._push(branch)
        pr_url = self._create_pr(event, branch) if pushed else None
        return {
            "status": "completed",
            "issue_id": event.issue_id,
            "branch": branch,
            "tests": self.test_command,
            "pushed": pushed,
            "pull_request_url": pr_url,
        }

    async def _audit(self, patches: list[PatchProposal]) -> list[str]:
        violations: list[str] = []
        for patch in patches:
            result = await PolicyEngine.evaluate_patch(
                patch.file_path, patch.content, [], "pending"
            )
            violations.extend(result.violations)
        return violations

    def _apply_patches(self, patches: list[PatchProposal]) -> None:
        for patch in patches:
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

    def _run_tests(self) -> "TestResult":
        result = subprocess.run(
            self.test_command,
            cwd=self.root,
            shell=True,
            capture_output=True,
            text=True,
            check=False,
        )
        return TestResult(result.returncode, result.stdout + result.stderr)

    def _git(self, *args: str) -> str:
        result = subprocess.run(
            ["git", *args], cwd=self.root, capture_output=True, text=True, check=False
        )
        if result.returncode:
            raise RuntimeError(f"git {' '.join(args)} failed: {result.stderr.strip()}")
        return result.stdout.strip()

    def _push(self, branch: str) -> bool:
        should_push = self.push
        if should_push is None:
            should_push = os.getenv("SDLC_PUSH", "false").lower() == "true"
        if not should_push:
            return False
        self._git("push", "-u", "origin", branch)
        return True

    def _create_pr(self, event: SDLCEvent, branch: str) -> Optional[str]:
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
        with request.urlopen(req, timeout=20) as response:
            return json.loads(response.read().decode())["html_url"]

    @staticmethod
    def _branch_name(event: SDLCEvent) -> str:
        slug = re.sub(r"[^a-z0-9]+", "-", event.title.lower()).strip("-")[:50]
        return f"feature/AGENT-{event.issue_id}-{slug or 'change'}"


class TestResult:
    def __init__(self, returncode: int, output: str):
        self.returncode = returncode
        self.output = output


def verify_github_signature(
    body: bytes, signature: Optional[str], secret: Optional[str]
) -> bool:
    if not secret:
        return True
    if not signature or not signature.startswith("sha256="):
        return False
    digest = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(signature[7:], digest)