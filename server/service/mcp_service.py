import logging
from typing import List
from langchain_core.tools import BaseTool
from contextlib import AsyncExitStack

from server.models.models import MCPServerConfig
from langchain_mcp_adapters.sessions import create_session
from langchain_mcp_adapters.tools import load_mcp_tools

logger = logging.getLogger(__name__)

class McpService:
    @staticmethod
    async def load_mcp_tools(server_configs: List[MCPServerConfig], exit_stack: AsyncExitStack) -> List[BaseTool]:
        all_tools = []
        for config in server_configs:
            try:
                connection = None
                if config.type == "command":
                    connection = {
                        "transport": "stdio",
                        "command": config.command,
                        "args": config.args or [],
                        "env": config.env or {}
                    }
                elif config.type == "sse":
                    connection = {
                        "transport": "sse",
                        "url": config.url
                    }
                elif config.type in ("streamable-http", "http"):
                    connection = {
                        "transport": "http",
                        "url": config.url
                    }
                
                if not connection:
                    continue

                logger.info(f"Connecting to MCP server: {config.name} ({config.type})")
                session = await exit_stack.enter_async_context(create_session(connection))
                await session.initialize()
                
                # Load tools using the adapter
                # We set tool_name_prefix=False because we'll add our own prefix to match existing logic
                tools = await load_mcp_tools(session)
                
                for tool in tools:
                    # Prefix tool name to avoid collisions and match backend event logic (mcp__)
                    original_name = tool.name
                    tool.name = f"mcp__{config.name}__{original_name}"
                    # Also update description if it's empty
                    if not tool.description:
                        tool.description = f"MCP tool {original_name} from server {config.name}"
                    
                    all_tools.append(tool)
                    
                logger.info(f"Successfully loaded {len(tools)} tools from MCP server: {config.name}")
            except Exception as e:
                logger.error(f"Failed to load MCP server {config.name}: {e}")
        return all_tools
