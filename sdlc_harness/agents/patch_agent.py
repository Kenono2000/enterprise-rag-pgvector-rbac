from typing import Any, Protocol, List
import json
from pydantic import BaseModel, Field
from app.db.llm import chat_completion


class PatchProposal(BaseModel):
    file_path: str = Field(min_length=1)
    content: str


class PatchAgent(Protocol):
    async def propose(self, payload: dict[str, Any]) -> list[PatchProposal]: ...

    async def repair(
        self, payload: dict[str, Any], test_output: str
    ) -> list[PatchProposal]: ...


class PayloadPatchAgent:
    """Deterministic adapter for typed patch proposals in a webhook payload."""

    async def propose(self, payload: dict[str, Any]) -> list[PatchProposal]:
        if "patches" in payload:
            return self._parse(payload.get("patches", []))
        
        # If no patches in payload, use LLM to generate them from issue description
        issue = payload.get("issue", {})
        title = issue.get("title", "")
        body = issue.get("body", "")
        repo = payload.get("repository", {}).get("full_name", "")
        
        prompt = f"""
        You are an autonomous SDLC agent. Given the following GitHub issue, propose a set of file patches to resolve it.
        
        Repository: {repo}
        Issue Title: {title}
        Issue Description: {body}
        
        Respond ONLY with a JSON list of patches, where each patch has 'file_path' and 'content'.
        Example:
        [
            {{"file_path": "src/main.py", "content": "print('hello world')"}}
        ]
        """
        
        response = await chat_completion(prompt)
        # Basic cleanup in case LLM adds markdown
        response = response.strip()
        if response.startswith("```json"):
            response = response[7:]
        if response.endswith("```"):
            response = response[:-3]
        
        try:
            raw_patches = json.loads(response)
            return self._parse(raw_patches)
        except Exception as e:
            raise ValueError(f"LLM failed to produce valid patch JSON: {str(e)}\nResponse: {response}")

    async def repair(
        self, payload: dict[str, Any], test_output: str
    ) -> list[PatchProposal]:
        if "repair_patches" in payload:
            return self._parse(payload.get("repair_patches", []))

        issue = payload.get("issue", {})
        title = issue.get("title", "")
        
        prompt = f"""
        You are an autonomous SDLC agent. You previously proposed patches for the issue: "{title}", 
        but the tests failed with the following output:
        
        {test_output}
        
        Propose a NEW set of file patches to fix the issue and resolve the test failures.
        Respond ONLY with a JSON list of patches, where each patch has 'file_path' and 'content'.
        """
        
        response = await chat_completion(prompt)
        response = response.strip()
        if response.startswith("```json"):
            response = response[7:]
        if response.endswith("```"):
            response = response[:-3]
            
        try:
            raw_patches = json.loads(response)
            return self._parse(raw_patches)
        except Exception as e:
            raise ValueError(f"LLM failed to produce valid repair patch JSON: {str(e)}")

    @staticmethod
    def _parse(raw_patches: Any) -> list[PatchProposal]:
        if not isinstance(raw_patches, list):
            raise ValueError("patches must be a JSON array")
        return [PatchProposal.model_validate(patch) for patch in raw_patches]