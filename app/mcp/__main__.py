"""
app/mcp/__main__.py
-------------------
Execution entry point for running the FastMCP gateway directly:
    python -m app.mcp
    python -m app.mcp --transport sse --port 8000
    python -m app.mcp --transport stdio
"""

from app.mcp.gateway import run_server

if __name__ == "__main__":
    run_server()

