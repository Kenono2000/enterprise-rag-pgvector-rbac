import asyncio
import io
import json
import sys
import os
from dotenv import load_dotenv
from fastmcp import Client
from fastmcp.client import BearerAuth


class HorizonAuth(BearerAuth):
    def __init__(self, token: str, roles: list[str]):
        super().__init__(token)
        self.roles = roles

    def auth_flow(self, request):
        request.headers["Authorization"] = f"Bearer {self.token.get_secret_value()}"
        request.headers["x-user-roles"] = json.dumps(self.roles)
        yield request


# Load environment variables from .env file
load_dotenv()

# Set stdout to UTF-8 to handle emojis in terminal
if sys.platform == "win32":
    if isinstance(sys.stdout, io.TextIOWrapper):
        sys.stdout.reconfigure(encoding="utf-8")

# Get API key from environment variable
api_key = os.getenv("HORIZON_API_KEY")

if not api_key:
    print("Error: HORIZON_API_KEY not found in .env file")
    sys.exit(1)

# Use Bearer authentication with the API key and include the simulated
# Auth0 role claim expected by the server's x-user-roles header.
client = Client(
    "https://enterprise-rag-mcp.fastmcp.app/mcp",
    auth=HorizonAuth(api_key, ["finance_executive"]),
)


async def main():
    try:
        async with client:
            print("Connected successfully!")

            # Listing tools validates the initialized MCP session. Some hosted
            # MCP servers do not expose the optional ping method.
            tools = await client.list_tools()
            print(f"Available tools: {len(tools)}")
            for tool in tools:
                print(f"  - {tool.name}")
            
            # Execute the tool call
            result = await client.call_tool(
                "search_knowledge_base",
                {
                    "question": "What were the Q3 financial results?",
                    "user_role": "finance_executive"
                }
            )
            print(f"Result: {result}")
            
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    asyncio.run(main())