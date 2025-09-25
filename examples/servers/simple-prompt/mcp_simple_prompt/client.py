import asyncio
from mcp.client.session import ClientSession
from mcp.client.sse import sse_client

import openziti

print(f"OpenZiti version: {openziti.__version__}")

# Load OpenZiti identity
openziti.load("/home/kbingham/Sites/mcp-python-sdk/simple-mcp-client.json")


async def main():
    # Use OpenZiti for the client call to the MCP server
    with openziti.monkeypatch():
        async with sse_client("http://prompt.mcp.nf.internal:8000/sse") as streams:
            async with ClientSession(*streams) as session:
                await session.initialize()

                # List available prompts
                prompts = await session.list_prompts()
                print(prompts)

                # Get the prompt with arguments
                prompt = await session.get_prompt(
                    "simple",
                    {
                        "context": "User is a software developer",
                        "topic": "Python async programming",
                    },
                )
                print(prompt)


if __name__ == "__main__":
    asyncio.run(main())
