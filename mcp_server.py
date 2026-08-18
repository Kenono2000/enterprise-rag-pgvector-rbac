"""
MCP Server for Zero-Trust Enterprise RAG.
Exposes the secure knowledge base as a tool for AI agents.
"""

from fastmcp import FastMCP
from engine import secure_search, DOCUMENTS_DB
import json

# Create an MCP server
mcp = FastMCP("Zero-Trust RAG")

# --- 1. TOOLS ---
@mcp.tool()
def search_knowledge_base(question: str, user_role: str) -> str:
    """
    Search the enterprise knowledge base using Zero-Trust RBAC.
    
    Args:
        question: The natural language question to ask.
        user_role: The simulated IAM role. [finance_executive, hr_manager, engineer, public_guest]
    """
    authorized_docs, error_msg = secure_search(question, user_role)
    
    if error_msg:
        return f"ACCESS_DENIED: {error_msg}"
    
    if not authorized_docs:
        return "No documents found or access denied for this query."
        
    # Return the top grounded result
    top_doc = authorized_docs[0]
    
    result_template = (
        f"✅ Authorization Verified\n"
        f"Source: {top_doc['title']}\n"
        f"Content: {top_doc['content']}\n"
        f"Relevance Score: {top_doc['similarity']}\n"
        f"Audit Info: Authorized for roles {top_doc['allowed_roles']}"
    )
    
    return result_template

# --- 2. RESOURCES ---
@mcp.resource("security://rbac-policy")
def get_rbac_policy() -> str:
    """Provides the current RBAC mapping and security policy for the RAG system."""
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
    """Returns a summary of the documents currently in the simulated database."""
    summary = [{"id": d["id"], "title": d["title"], "roles": d["allowed_roles"]} for d in DOCUMENTS_DB]
    return f"Current Knowledge Base Manifest:\n{json.dumps(summary, indent=2)}"

# --- 3. PROMPTS ---
@mcp.prompt("security-audit")
def audit_prompt():
    """Sets up a scenario to test the Zero-Trust RBAC boundaries."""
    return """You are a Security Compliance Auditor. Your goal is to verify that the Zero-Trust RAG system correctly enforces RBAC.

Please perform the following tests:
1. Try to access 'Financial Audit' documents while acting as an 'engineer'.
2. Verify that a 'public_guest' can see 'Public Engineering Standards'.
3. Report any cases where the 'search_knowledge_base' tool returns data that doesn't match the 'security://rbac-policy' resource.

How would you like to begin the audit?"""

@mcp.prompt("financial-analysis")
def finance_prompt(company_quarter: str = "Q3"):
    """Templates a request for financial analysis as an executive."""
    return f"""I am acting as a 'finance_executive'. 
Please search the knowledge base for {company_quarter} financial results and provide a summary of the operating margins. 
Cross-reference the results with the current security policy."""

if __name__ == "__main__":
    # To run this in debug mode with a UI: fastmcp dev mcp_server.py
    mcp.run()

# fastmcp dev .\mcp_server.py
# npm i @modelcontextprotocol/inspector@latest