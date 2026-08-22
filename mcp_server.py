from fastmcp import FastMCP
from engine import secure_search, DOCUMENTS_DB
import json
import os

mcp = FastMCP("Zero-Trust RAG")

@mcp.tool()
def search_knowledge_base(question: str, user_role: str) -> str:
    authorized_docs, error_msg = secure_search(question, user_role)
    if error_msg:
        return f"ACCESS_DENIED: {error_msg}"
    if not authorized_docs:
        return "No documents found or access denied for this query."
    
    top_doc = authorized_docs[0]
    result_template = (
        f"✅ Authorization Verified\n"
        f"Source: {top_doc['title']}\n"
        f"Content: {top_doc['content']}\n"
        f"Relevance Score: {top_doc['similarity']}\n"
        f"Audit Info: Authorized for roles {top_doc['allowed_roles']}"
    )
    return result_template

@mcp.resource("security://rbac-policy")
def get_rbac_policy() -> str:
    policy = {
        "system_name": "Zero-Trust Enterprise RAG",
        "enforcement_level": "In-Database Row Level Security (RLS)",
        "role_definitions": {
            "finance_executive": "Access to Q3/Q4 Financial Audits and Executive reports.",
            "hr_manager": "Access to Compensation benchmarks and internal policies.",
            "engineer": "Access to Technical standards and public docs.",
            "public_guest": "Access to documents marked 'public' only."
        }
    }
    return json.dumps(policy, indent=2)

@mcp.resource("system://manifest")
def get_manifest() -> str:
    summary = [{"id": d["id"], "title": d["title"], "roles": d["allowed_roles"]} for d in DOCUMENTS_DB]
    return f"Current Knowledge Base Manifest:\n{json.dumps(summary, indent=2)}"

@mcp.prompt("security-audit")
def audit_prompt():
    return "Perform a security audit on the current RBAC policies and document access logs."

@mcp.prompt("financial-analysis")
def finance_prompt(company_quarter: str = "Q3"):
    return f"Analyze the financial performance for {company_quarter}."

if __name__ == "__main__":
    # Use SSE transport if PORT is provided (for cloud deployment like Render/Railway), 
    # otherwise default to stdio for local Claude Desktop integration.
    if "PORT" in os.environ:
        port = int(os.environ.get("PORT", 8000))
        print(f"🚀 Starting MCP SSE server on port {port}...")
        mcp.run(transport="sse", host="0.0.0.0", port=port)
    else:
        print("🖥️ Starting MCP server in stdio mode (for local Claude Desktop integration)...")
        mcp.run()