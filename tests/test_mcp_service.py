import asyncio
import json

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


def test_mcp_tool_router_returns_error_payload_for_ambiguous_tools():
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

        result = await call_tool.ainvoke(
            {"tool_name": "read", "arguments": {"path": "README.md"}}
        )
        payload = json.loads(result)
        assert payload["ok"] is False
        assert payload["tool_name"] == "read"
        assert payload["resolved_tool_name"] is None
        assert payload["error"]["type"] == "ValueError"
        assert "Ambiguous MCP tool name" in payload["error"]["message"]

    asyncio.run(run())


def test_mcp_tool_router_returns_error_payload_for_failed_tool_call():
    async def run():
        async def fetch_url(url: str) -> str:
            raise RuntimeError(f"Unable to fetch {url}")

        real_tool = StructuredTool.from_function(
            coroutine=fetch_url,
            name="mcp__web__fetch_url",
            description="Fetch a URL and return the response body.",
        )
        real_tool.metadata = {"mcp_server": "web", "mcp_tool": "fetch_url"}

        call_tool = McpToolRouter([real_tool]).as_tools()[1]
        result = await call_tool.ainvoke(
            {
                "tool_name": "mcp__web__fetch_url",
                "arguments": {"url": "https://example.test"},
            }
        )
        payload = json.loads(result)

        assert payload["ok"] is False
        assert payload["tool_name"] == "mcp__web__fetch_url"
        assert payload["resolved_tool_name"] == "mcp__web__fetch_url"
        assert payload["error"]["type"] == "RuntimeError"
        assert "Unable to fetch https://example.test" in payload["error"]["message"]

    asyncio.run(run())


def test_mcp_tool_router_returns_error_payload_for_invalid_call_arguments():
    async def run():
        async def fetch_url(url: str) -> str:
            return url

        real_tool = StructuredTool.from_function(
            coroutine=fetch_url,
            name="mcp__web__fetch_url",
            description="Fetch a URL and return the response body.",
        )
        real_tool.metadata = {"mcp_server": "web", "mcp_tool": "fetch_url"}

        call_tool = McpToolRouter([real_tool]).as_tools()[1]
        result = await call_tool.ainvoke({"arguments": {"url": "https://example.test"}})
        payload = json.loads(result)

        assert payload["ok"] is False
        assert payload["tool_name"] == "mcp_call"
        assert payload["resolved_tool_name"] is None
        assert "tool_name" in payload["error"]["message"]

    asyncio.run(run())
