import json
from dataclasses import dataclass
from typing import Any, Dict, Optional

from mcp import ClientSession, StdioServerParameters
from mcp.shared.exceptions import McpError
from mcp.client.stdio import stdio_client

from .config import settings


@dataclass
class NotionMCPConfig:
    command: Optional[str]
    args: list[str]


class NotionMCPClient:
    def __init__(self, config: Optional[NotionMCPConfig] = None) -> None:
        if config is None:
            config = NotionMCPConfig(
                command=settings.notion_mcp_command,
                args=settings.notion_mcp_args,
            )
        self.config = config

    def _validate(self) -> None:
        if not self.config.command:
            raise RuntimeError("NOTION_MCP_COMMAND is not configured")

    async def list_tools(self) -> Dict[str, Any]:
        self._validate()
        server_params = StdioServerParameters(
            command=self.config.command,
            args=self.config.args,
            env=None,
        )
        try:
            async with stdio_client(server_params) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    result = await session.list_tools()
            tools = result.tools if hasattr(result, "tools") else result
            serialized = []
            for tool in tools or []:
                serialized.append(
                    {
                        "name": getattr(tool, "name", None),
                        "description": getattr(tool, "description", None),
                        "input_schema": getattr(tool, "input_schema", None),
                    }
                )
            return {"tools": serialized}
        except McpError as exc:
            return {"error": str(exc)}

    async def call_tool(self, name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        self._validate()
        server_params = StdioServerParameters(
            command=self.config.command,
            args=self.config.args,
            env=None,
        )
        try:
            async with stdio_client(server_params) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    result = await session.call_tool(name=name, arguments=arguments)
        except McpError as exc:
            return {"error": str(exc)}
        if hasattr(result, "content"):
            return {"content": result.content}
        try:
            return json.loads(str(result))
        except json.JSONDecodeError:
            return {"content": str(result)}
