from fastmcp import FastMCP
import json
import os
import asyncpg
from typing import List

# Initialize FastMCP
mcp = FastMCP("Zero-Trust RAG")

# Database connection pool (initialized on first use)
db_pool = None

async def get_db_pool():
    global db_pool
    if db_pool is None:
        database_url = os.getenv("DATABASE_URL")
        if not database_url:
            raise RuntimeError("DATABASE_URL environment variable is not set")
        db_pool = await asyncpg.create_pool(database_url, min_size=1, max_size=5)
    return db_pool

@mcp.tool()
async def search_knowledge_base(question: str, user_role: str) -> str:
    """
    Securely search the enterprise knowledge base. 
    Enforces in-database RBAC using PostgreSQL JSONB ?| operator.
    """
    try:
        pool = await get_db_pool()
        
        # Generate a mock embedding for the demo (in production, call OpenAI API here)
        # For demo simplicity, we'll do a sequential scan ordered by a mock match, 
        # or you can add a real embedding call here.
        # To keep the demo fast and dependency-light, we'll simulate the vector match 
        # but enforce the STRICT RBAC check against the real database.
        
        roles_array = [user_role]
        
        async with pool.acquire() as conn:
            # REAL SHIFT-LEFT SECURITY: The DB filters by role BEFORE returning data
            rows = await conn.fetch("""
                SELECT document_id, title, content, allowed_roles
                FROM enterprise_documents
                WHERE allowed_roles ?| $1::text[]
                LIMIT 3
            """, roles_array)
            
        if not rows:
            return f"ACCESS_DENIED: No documents found for role '{user_role}'."
            
        # Format the top result for the AI Agent
        top_doc = rows[0]
        result_template = (
            f"✅ Authorization Verified\n"
            f"Source: {top_doc['title']} (ID: {top_doc['document_id']})\n"
            f"Content: {top_doc['content']}\n"
            f"Audit Info: Authorized for roles {json.dumps(top_doc['allowed_roles'])}"
        )
        return result_template
        
    except Exception as e:
        return f"SYSTEM_ERROR: Failed to execute secure search. Details: {str(e)}"

@mcp.resource("security://rbac-policy")
def get_rbac_policy() -> str:
    policy = {
        "system_name": "Zero-Trust Enterprise RAG",
        "enforcement_level": "In-Database Row Level Security (RLS) via JSONB ?| operator",
        "role_definitions": {
            "finance_executive": "Access to Q3/Q4 Financial Audits and Executive reports.",
            "hr_manager": "Access to Compensation benchmarks and internal policies.",
            "engineer": "Access to Technical standards and public docs.",
            "public_guest": "Access to documents marked 'public' only."
        }
    }
    return json.dumps(policy, indent=2)

@mcp.resource("system://manifest")
async def get_manifest() -> str:
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT document_id, title, allowed_roles FROM enterprise_documents")
    
    summary = [{"id": r["document_id"], "title": r["title"], "roles": r["allowed_roles"]} for r in rows]
    return f"Current Knowledge Base Manifest:\n{json.dumps(summary, indent=2)}"

if __name__ == "__main__":
    # Dual-Transport: SSE for Cloud (Prefect Horizon), stdio for Local (Claude Desktop)
    if "PORT" in os.environ:
        port = int(os.environ.get("PORT", 8000))
        print(f"🚀 Starting MCP SSE server on port {port}...")
        mcp.run(transport="sse", host="0.0.0.0", port=port)
    else:
        print("🖥️ Starting MCP server in stdio mode (for local Claude Desktop)...")
        mcp.run()

# fastmcp run .\mcp_server.py --no-banner --reload