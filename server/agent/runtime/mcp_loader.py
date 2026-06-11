"""MCP tool loading helpers for agent runs."""

import json
from contextlib import AsyncExitStack
from collections.abc import Callable
from typing import Any

from langchain_core.tools import BaseTool, StructuredTool
from pydantic import BaseModel, Field
from sqlalchemy import select

from server.core.logger import logger
from server.db import AsyncSessionLocal
from server.models.mcp import MCPServerConfig
from server.service.mcp_service import McpService, McpToolRouter


class DynamicMcpSearchInput(BaseModel):
    query: str = Field(default="")
    server: str | None = Field(default=None)
    limit: int = Field(default=10, ge=1, le=25)
    include_schema: bool = Field(default=False)


class DynamicMcpCallInput(BaseModel):
    tool_name: str
    arguments: dict[str, Any] = Field(default_factory=dict)


async def load_mcp_tools(
    server_names: list[str] | None,
    exit_stack: AsyncExitStack,
) -> list[Any]:
    if not server_names:
        return []

    logger.info("Loading tools from MCP servers: %s", server_names)
    async with AsyncSessionLocal() as db_session:
        mcp_configs_result = await db_session.execute(
            select(MCPServerConfig).where(MCPServerConfig.name.in_(server_names))
        )
        found_configs = mcp_configs_result.scalars().all()

    if not found_configs:
        return []
    return await McpService.load_lazy_mcp_tools(found_configs, exit_stack)


def create_dynamic_mcp_router_tools(
    server_names_provider: Callable[[], list[str] | None],
) -> list[BaseTool]:
    """Create stable MCP router tools whose server list is read at call time."""

    async def mcp_search(
        query: str = "",
        server: str | None = None,
        limit: int = 10,
        include_schema: bool = False,
    ) -> str:
        """Search enabled MCP tools before calling one with mcp_call."""
        server_names = server_names_provider() or []
        if not server_names:
            return _no_mcp_servers_result()

        async with AsyncExitStack() as exit_stack:
            router = await _load_mcp_router(server_names, exit_stack)
            if router is None:
                return _no_mcp_servers_result()
            return router.search(
                query=query,
                server=server,
                limit=limit,
                include_schema=include_schema,
            )

    async def mcp_call(
        tool_name: str,
        arguments: dict[str, Any] | None = None,
        callbacks: Any = None,
    ) -> str:
        """Call one enabled MCP tool by exact name with JSON arguments."""
        server_names = server_names_provider() or []
        if not server_names:
            return _mcp_call_error(tool_name, "No MCP servers are configured.")

        async with AsyncExitStack() as exit_stack:
            router = await _load_mcp_router(server_names, exit_stack)
            if router is None:
                return _mcp_call_error(tool_name, "No MCP tools are available.")
            return await router.call(
                tool_name=tool_name,
                arguments=arguments or {},
                callbacks=callbacks,
            )

    return [
        StructuredTool.from_function(
            coroutine=mcp_search,
            name="mcp_search",
            description=(
                "Search the MCP servers configured for the current agent. Use "
                "this before mcp_call when you need an external MCP capability "
                "or an exact argument schema."
            ),
            args_schema=DynamicMcpSearchInput,
        ),
        StructuredTool.from_function(
            coroutine=mcp_call,
            name="mcp_call",
            description=(
                "Call one MCP tool returned by mcp_search. Pass tool_name "
                "exactly as returned and provide arguments as a JSON object."
            ),
            args_schema=DynamicMcpCallInput,
        ),
    ]


async def _load_mcp_router(
    server_names: list[str],
    exit_stack: AsyncExitStack,
) -> McpToolRouter | None:
    configs = await _load_mcp_configs(server_names)
    if not configs:
        return None

    tools = await McpService.load_mcp_tools(configs, exit_stack)
    if not tools:
        return None
    return McpToolRouter(tools)


async def _load_mcp_configs(server_names: list[str]) -> list[MCPServerConfig]:
    logger.info("Loading tools from MCP servers: %s", server_names)
    async with AsyncSessionLocal() as db_session:
        result = await db_session.execute(
            select(MCPServerConfig).where(MCPServerConfig.name.in_(server_names))
        )
        return list(result.scalars().all())


def _no_mcp_servers_result() -> str:
    return json.dumps(
        {
            "tools": [],
            "count": 0,
            "total_available": 0,
            "hint": "No MCP servers are configured for the current agent.",
        },
        ensure_ascii=False,
    )


def _mcp_call_error(tool_name: str, message: str) -> str:
    return json.dumps(
        {
            "ok": False,
            "tool_name": tool_name,
            "resolved_tool_name": None,
            "error": {"type": "MCPUnavailable", "message": message},
            "hint": "Call mcp_search after enabling an MCP server for this agent.",
        },
        ensure_ascii=False,
    )
