import sys
import os

# Add the project root (2 levels up from this file) to the Python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from fastmcp import FastMCP
from app.db.manager import DatabaseManager
import json

mcp = FastMCP("SDLC-Harness-Gateway")

@mcp.tool()
async def search_sdlc_context(question: str, user_role: str) -> str:
    """
    Search the knowledge base for SDLC context (ADRs, standards, policies).
    """
    # This would call the embedding + DB manager logic
    # Simplified for the tool interface
    return f"Context for {question} (Role: {user_role})"

@mcp.tool()
async def propose_patch(branch_name: str, patch_content: str) -> str:
    """
    Submit a code patch for review.
    """
    return f"Patch submitted to {branch_name}"

@mcp.resource("policy://sdlc-budget")
def get_budget_policy() -> str:
    return json.dumps({
        "max_tokens_per_issue": 50000,
        "max_steps": 10,
        "allowed_tools": ["search_sdlc_context", "propose_patch"]
    })
