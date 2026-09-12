import sys
import os

# Add the project root (2 levels up from this file) to the Python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from fastmcp import FastMCP
from app.db.manager import DatabaseManager
from app.db.llm import generate_embedding, chat_completion
import json

mcp = FastMCP("SDLC-Harness-Gateway")

@mcp.tool()
async def search_sdlc_context(question: str, user_roles: list[str] = ["finance_executive"]) -> str:
    """
    Search the knowledge base for SDLC context (ADRs, standards, policies).
    user_roles: List of roles (e.g. ["admin", "developer"])
    """
    query_vector = await generate_embedding(question)
    rows = await DatabaseManager.secure_search(query_vector, user_roles)
    
    if not rows:
        return "No authorized documentation found for the given question and roles."
        
    context_chunks = "\n\n".join([f"[{r['title']}]: {r['content']}" for r in rows])
    
    prompt = f"Answer strictly using context:\n\n{context_chunks}\n\nQuestion: {question}"
    answer_text = await chat_completion(prompt)
    
    citations = [f"- {r['title']} (similarity: {round(float(r['similarity']), 3)})" for r in rows]
    citations_text = "\n".join(citations)
    
    return f"{answer_text}\n\nCitations:\n{citations_text}"

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

if __name__ == "__main__":
    mcp.run()