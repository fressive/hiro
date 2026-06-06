import asyncio
import json

import pytest
from langchain_core.tools import StructuredTool

from server.service.mcp_service import McpToolRouter


def test_mcp_tool_router_exposes_compact_proxy_tools():
    async def run():
        async def fetch_url(url: str, timeout: int = 5) -> str:
            return f"fetched {url} in {timeout}s"

        real_tool = StructuredTool.from_function(
            coroutine=fetch_url,
            name="mcp__web__fetch_url",
            description="Fetch a URL and return the response body.",
        )
        real_tool.metadata = {"mcp_server": "web", "mcp_tool": "fetch_url"}

        proxy_tools = McpToolRouter([real_tool]).as_tools()

        assert [tool.name for tool in proxy_tools] == ["mcp_search", "mcp_call"]
        proxy_schema = json.dumps(
            proxy_tools[1].tool_call_schema.model_json_schema(),
            sort_keys=True,
        )
        assert "fetch_url" not in proxy_schema

        search_result = await proxy_tools[0].ainvoke(
            {"query": "fetch", "include_schema": True}
        )
        payload = json.loads(search_result)
        assert payload["tools"][0]["name"] == "mcp__web__fetch_url"
        assert payload["tools"][0]["server"] == "web"
        assert "url" in payload["tools"][0]["schema"]["properties"]

        call_result = await proxy_tools[1].ainvoke(
            {
                "tool_name": "mcp__web__fetch_url",
                "arguments": {"url": "https://example.test", "timeout": 3},
            }
        )
        assert call_result == "fetched https://example.test in 3s"

    asyncio.run(run())


def test_mcp_tool_router_requires_full_name_for_ambiguous_tools():
    async def run():
        async def read(path: str) -> str:
            return path

        first_tool = StructuredTool.from_function(
            coroutine=read,
            name="mcp__files__read",
            description="Read a file.",
        )
        first_tool.metadata = {"mcp_server": "files", "mcp_tool": "read"}
        second_tool = StructuredTool.from_function(
            coroutine=read,
            name="mcp__docs__read",
            description="Read a document.",
        )
        second_tool.metadata = {"mcp_server": "docs", "mcp_tool": "read"}

        call_tool = McpToolRouter([first_tool, second_tool]).as_tools()[1]

        with pytest.raises(ValueError, match="Ambiguous MCP tool name"):
            await call_tool.ainvoke(
                {"tool_name": "read", "arguments": {"path": "README.md"}}
            )

    asyncio.run(run())
