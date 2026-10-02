"""
app/mcp/__main__.py
-------------------
Execution entry point for running the FastMCP gateway directly:
    python -m app.mcp
"""

from app.mcp.gateway import mcp

if __name__ == "__main__":
    mcp.run()
