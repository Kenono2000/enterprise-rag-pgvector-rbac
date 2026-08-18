"""
Minimal MCP Server for Enterprise RAG.
Provides basic health check and connectivity testing tools.
"""

from fastmcp import FastMCP

# Initialize the MCP server with a descriptive name
mcp = FastMCP("Minimal RAG Gateway")

@mcp.tool()
def health_check() -> str:
    """
    Verifies that the MCP server is operational and responding.
    Returns a simple status message.
    """
    return "✅ Minimal RAG Gateway is online and ready."

@mcp.tool()
def echo_message(message: str = "Hello World") -> str:
    """
    Echoes back a message to verify connectivity and parameter parsing.
    
    Args:
        message: The string to be returned by the server.
    """
    return f"Echo: {message}"

if __name__ == "__main__":
    # Start the server using the standard I/O transport
    mcp.run()

# fastmcp dev .\min_mcp_server.py
# npm i @modelcontextprotocol/inspector@latest