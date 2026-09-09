from typing import Any, Protocol

from pydantic import BaseModel, Field


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
        return self._parse(payload.get("patches", []))

    async def repair(
        self, payload: dict[str, Any], test_output: str
    ) -> list[PatchProposal]:
        return self._parse(payload.get("repair_patches", []))

    @staticmethod
    def _parse(raw_patches: Any) -> list[PatchProposal]:
        if not isinstance(raw_patches, list):
            raise ValueError("patches must be a JSON array")
        return [PatchProposal.model_validate(patch) for patch in raw_patches]