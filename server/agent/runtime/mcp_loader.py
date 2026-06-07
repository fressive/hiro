"""MCP tool loading for agent runs."""

from contextlib import AsyncExitStack
from typing import Any

from sqlalchemy import select

from server.core.logger import logger
from server.db import AsyncSessionLocal
from server.models.mcp import MCPServerConfig
from server.service.mcp_service import McpService


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
