from pydantic import BaseModel, Field, field_validator
from fastmcp import FastMCP
import os

mcp_sdlc = FastMCP("Autonomous-SDLC-Harness")

class PatchFileDTO(BaseModel):
    branch_name: str = Field(..., pattern=r"^feature/AGENT-[0-9]{3,6}-[a-z0-9\-]+$")
    file_path: str = Field(..., description="Relative repository file path")
    content: str = Field(..., description="Exact file contents")

    @field_validator("file_path")
    @classmethod
    def prevent_traversal(cls, v: str) -> str:
        if ".." in v or v.startswith("/") or v.startswith(".git"):
            raise ValueError("Path traversal or tampering with .git/ is forbidden.")
        return v

@mcp_sdlc.tool()
async def apply_code_patch(dto: PatchFileDTO) -> str:
    """Writes code modifications strictly inside an isolated workspace."""
    # Ensure sandbox root exists (in production this would be a mounted volume)
    sandbox_root = os.getenv("SDLC_SANDBOX_ROOT", "/workspace/sandbox")
    safe_path = os.path.normpath(os.path.join(sandbox_root, dto.file_path))
    
    # Double check safe_path is within sandbox_root
    if not safe_path.startswith(os.path.abspath(sandbox_root)):
         return f"ERROR: Path {dto.file_path} resolved outside of sandbox."

    try:
        os.makedirs(os.path.dirname(safe_path), exist_ok=True)
        with open(safe_path, "w", encoding="utf-8") as f:
            f.write(dto.content)
        return f"Applied update to {dto.file_path} on {dto.branch_name}."
    except Exception as e:
        return f"SYSTEM_ERROR: Failed to apply patch: {str(e)}"
