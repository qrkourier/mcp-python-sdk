import asyncio
import json
from datetime import datetime
from typing import Any

import anyio
import click
import httpx
import mcp.types as types
from mcp.server.lowlevel import Server
from starlette.requests import Request


class GitHubStatusMonitor:
    def __init__(self):
        self.last_status: dict[str, Any] | None = None
        self.monitoring = False
        self.check_interval = 300  # 5 minutes
        self.status_url = "https://www.githubstatus.com/api/v2/summary.json"
        
    async def check_status(self) -> dict[str, Any]:
        """Check GitHub status and return summary."""
        async with httpx.AsyncClient() as client:
            response = await client.get(self.status_url)
            response.raise_for_status()
            return response.json()
    
    async def get_current_status(self) -> dict[str, Any]:
        """Get current status information."""
        try:
            status_data = await self.check_status()
            return {
                "status": status_data.get("status", {}).get("indicator", "unknown"),
                "description": status_data.get("status", {}).get("description", "No description"),
                "updated_at": status_data.get("page", {}).get("updated_at", "unknown"),
                "incidents": len(status_data.get("incidents", [])),
                "maintenances": len(status_data.get("scheduled_maintenances", []))
            }
        except Exception as e:
            return {
                "status": "error",
                "description": f"Failed to fetch status: {str(e)}",
                "updated_at": datetime.now().isoformat(),
                "incidents": 0,
                "maintenances": 0
            }

# Global monitor instance
github_monitor = GitHubStatusMonitor()


async def monitor_github_status():
    """Background task to monitor GitHub status and detect problems."""
    while github_monitor.monitoring:
        try:
            current_status = await github_monitor.get_current_status()
            
            # Check if status indicates a problem
            if current_status["status"] not in ["none", "minor"]:
                # Status indicates major/critical issues
                alert_msg = (f"GitHub Status Alert: {current_status['status']} - "
                           f"{current_status['description']}")
                print(alert_msg)
                
            # Check for active incidents
            if current_status["incidents"] > 0:
                incident_msg = (f"GitHub Incidents Alert: "
                              f"{current_status['incidents']} active incidents")
                print(incident_msg)
                
            github_monitor.last_status = current_status
            await asyncio.sleep(github_monitor.check_interval)
            
        except Exception as e:
            print(f"Error monitoring GitHub status: {e}")
            await asyncio.sleep(60)  # Wait 1 minute on error


@click.command()
@click.option("--port", default=8000, help="Port to listen on for SSE")
@click.option(
    "--transport",
    type=click.Choice(["stdio", "sse"]),
    default="stdio",
    help="Transport type",
)
def main(port: int, transport: str) -> int:
    app = Server("mcp-github-status-monitor")

    @app.call_tool()
    async def github_status_tool(name: str, arguments: dict[str, Any]) -> list[types.ContentBlock]:
        if name == "check_github_status":
            status = await github_monitor.get_current_status()
            status_text = json.dumps(status, indent=2)
            return [types.TextContent(type="text", text=f"GitHub Status:\n{status_text}")]
        
        elif name == "start_monitoring":
            interval = arguments.get("interval", 300)  # Default 5 minutes
            github_monitor.check_interval = interval
            github_monitor.monitoring = True
            
            # Start background monitoring task
            asyncio.create_task(monitor_github_status())
            
            return [types.TextContent(
                type="text", 
                text=f"Started GitHub status monitoring with {interval}s interval"
            )]
        
        elif name == "stop_monitoring":
            github_monitor.monitoring = False
            return [types.TextContent(
                type="text", 
                text="Stopped GitHub status monitoring"
            )]
        
        else:
            raise ValueError(f"Unknown tool: {name}")

    @app.list_tools()
    async def list_tools() -> list[types.Tool]:
        return [
            types.Tool(
                name="check_github_status",
                title="Check GitHub Status",
                description="Get current GitHub service status",
                inputSchema={"type": "object"},
            ),
            types.Tool(
                name="start_monitoring",
                title="Start GitHub Status Monitoring",
                description="Start periodic monitoring of GitHub status",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "interval": {
                            "type": "integer",
                            "description": "Check interval in seconds (default: 300)",
                            "minimum": 10
                        }
                    },
                },
            ),
            types.Tool(
                name="stop_monitoring",
                title="Stop GitHub Status Monitoring", 
                description="Stop periodic monitoring of GitHub status",
                inputSchema={"type": "object"},
            )
        ]

    if transport == "sse":
        from mcp.server.sse import SseServerTransport
        from starlette.applications import Starlette
        from starlette.responses import Response
        from starlette.routing import Mount, Route

        sse = SseServerTransport("/messages/")

        async def handle_sse(request: Request):
            async with sse.connect_sse(request.scope, request.receive, request._send) as streams:  # type: ignore[reportPrivateUsage]
                await app.run(streams[0], streams[1], app.create_initialization_options())
            return Response()

        starlette_app = Starlette(
            debug=True,
            routes=[
                Route("/sse", endpoint=handle_sse, methods=["GET"]),
                Mount("/messages/", app=sse.handle_post_message),
            ],
        )

        import uvicorn
        import openziti
        cfg = dict(
            ztx="simple-mcp-host.json",
            service="simple-mcp-tool"
        )
        openziti.monkeypatch(bindings={("127.0.0.1", port): cfg})
        uvicorn.run(starlette_app, host="127.0.0.1", port=port)
    else:
        from mcp.server.stdio import stdio_server

        async def arun():
            async with stdio_server() as streams:
                await app.run(streams[0], streams[1], app.create_initialization_options())

        anyio.run(arun)

    return 0
