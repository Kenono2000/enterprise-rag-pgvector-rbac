import os
import sys
import json
import logging
from pathlib import Path
from typing import Optional, List, Tuple

# Add the project root to sys.path to allow absolute imports of the 'app' package
# when this file is run as a standalone script (e.g., by fastmcp inspect).
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from dotenv import load_dotenv, find_dotenv
load_dotenv(find_dotenv(), override=True)

from fastmcp import FastMCP
from app.db.manager import DatabaseManager
from app.db.llm import generate_embedding, chat_completion
from app.auth.jwks import verify_google_token
from app.auth.role_mapper import extract_roles

logger = logging.getLogger(__name__)

mcp = FastMCP("SDLC-Harness-Gateway")


def _resolve_tool_roles(
    auth_token: Optional[str] = None,
    user_roles: Optional[List[str]] = None,
) -> Tuple[Optional[List[str]], Optional[str]]:
    """
    Resolve and verify application roles for an MCP tool invocation.

    Returns:
        (roles, error_message)
    """
    require_google = os.getenv("REQUIRE_GOOGLE_AUTH", "false").lower() == "true"

    if auth_token:
        try:
            payload = verify_google_token(auth_token)
            roles = extract_roles(payload)
            logger.info("MCP authenticated sub=%s roles=%s", payload.get("sub"), roles)
            return roles, None
        except Exception as exc:
            logger.warning("MCP token verification failed: %s", exc)
            return None, f"Token verification failed: {str(exc)}"

    if require_google:
        return None, "Authorization required: provide a valid Google ID token via 'auth_token'."

    # Dev/testing fallback when REQUIRE_GOOGLE_AUTH=false
    fallback_roles = user_roles if user_roles is not None else ["finance_executive"]
    logger.debug("MCP unauthenticated fallback using roles: %s", fallback_roles)
    return fallback_roles, None


@mcp.tool()
async def search_sdlc_context(
    question: str,
    auth_token: Optional[str] = None,
    user_roles: Optional[list[str]] = None,
) -> str:
    """
    Search the knowledge base for SDLC context (ADRs, standards, policies).

    Parameters:
    - question: Natural language question or search query.
    - auth_token: Optional Google ID token. If supplied, application roles are cryptographically
      verified via Google JWKS.
    - user_roles: Optional fallback roles list (only honored if REQUIRE_GOOGLE_AUTH=false).
    """
    roles, error = _resolve_tool_roles(auth_token, user_roles)
    if error:
        return f"⛔ {error}"

    query_vector = await generate_embedding(question)
    rows = await DatabaseManager.secure_search(query_vector, roles)

    if not rows:
        return f"No authorized documentation found for the evaluated roles: {roles}"

    context_chunks = "\n\n".join([f"[{r['title']}]: {r['content']}" for r in rows])

    prompt = f"Answer strictly using context:\n\n{context_chunks}\n\nQuestion: {question}"
    answer_text = await chat_completion(prompt)

    citations = [f"- {r['title']} (similarity: {round(float(r['similarity']), 3)})" for r in rows]
    citations_text = "\n".join(citations)

    return f"{answer_text}\n\nCitations:\n{citations_text}\n\n[Authorized Roles Evaluated: {roles}]"


@mcp.tool()
async def propose_patch(
    branch_name: str,
    patch_content: str,
    auth_token: Optional[str] = None,
) -> str:
    """
    Submit a code patch for review.

    Parameters:
    - branch_name: Target git branch name.
    - patch_content: The patch content.
    - auth_token: Optional Google ID token to verify submitter identity.
    """
    submitter = "anonymous"
    if auth_token:
        try:
            payload = verify_google_token(auth_token)
            submitter = payload.get("email") or payload.get("sub", "authenticated-user")
        except Exception as exc:
            return f"⛔ Authentication failed: {str(exc)}"
    elif os.getenv("REQUIRE_GOOGLE_AUTH", "false").lower() == "true":
        return "⛔ Authorization required: provide a valid Google ID token via 'auth_token'."

    return f"Patch submitted to {branch_name} by {submitter}"


@mcp.resource("policy://sdlc-budget")
def get_budget_policy() -> str:
    return json.dumps({
        "max_tokens_per_issue": 50000,
        "max_steps": 10,
        "allowed_tools": ["search_sdlc_context", "propose_patch"]
    })


if __name__ == "__main__":
    mcp.run()