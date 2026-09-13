from fastmcp import FastMCP
mcp = FastMCP("Minimal RAG Gateway")
@mcp.tool()
def health_check() -> str:
    return "✅ Minimal RAG Gateway is online and ready."
@mcp.tool()
def echo_message(message: str = "Hello World") -> str:
    return f"Echo: {message}"
if __name__ == "__main__":
    mcp.run()