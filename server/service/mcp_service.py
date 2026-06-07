import json
import logging
from typing import Any, List
from langchain_core.tools import BaseTool
from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field
from contextlib import AsyncExitStack

from server.models.mcp import MCPServerConfig
from langchain_mcp_adapters.sessions import create_session
from langchain_mcp_adapters.tools import load_mcp_tools

logger = logging.getLogger(__name__)

_MCP_TOOL_NAME_PREFIX = "mcp__"
_MAX_SEARCH_RESULTS = 25
_MAX_DESCRIPTION_CHARS = 700
_MAX_SCHEMA_CHARS = 6000
_MAX_TOOL_OUTPUT_CHARS = 20000


class McpSearchInput(BaseModel):
    query: str = Field(
        default="",
        description="Keywords for MCP tool names, descriptions, or servers.",
    )
    server: str | None = Field(
        default=None,
        description="Optional MCP server name to restrict the search.",
    )
    limit: int = Field(
        default=10,
        ge=1,
        le=_MAX_SEARCH_RESULTS,
        description="Maximum number of tool summaries to return.",
    )
    include_schema: bool = Field(
        default=False,
        description="Return full argument schemas for matched tools.",
    )


class McpCallInput(BaseModel):
    tool_name: str = Field(
        description=(
            "Exact MCP tool name. Prefer the full name returned by mcp_search, "
            "for example mcp__server__tool."
        )
    )
    arguments: dict[str, Any] = Field(
        default_factory=dict,
        description="JSON object passed as arguments to the selected MCP tool.",
    )


class McpToolRouter:
    """Expose many MCP tools through a compact search/call interface."""

    def __init__(self, tools: list[BaseTool]):
        self._tools = list(tools)
        self._tools_by_name = {tool.name: tool for tool in self._tools}
        self._tool_infos = [self._build_tool_info(tool) for tool in self._tools]

    def as_tools(self) -> list[BaseTool]:
        async def mcp_search(
            query: str = "",
            server: str | None = None,
            limit: int = 10,
            include_schema: bool = False,
        ) -> str:
            """Search enabled MCP tools before calling one with mcp_call."""
            return self.search(
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
            """Call one MCP tool by exact name with JSON arguments."""
            return await self.call(
                tool_name=tool_name,
                arguments=arguments or {},
                callbacks=callbacks,
            )

        search_tool = StructuredTool.from_function(
            coroutine=mcp_search,
            name="mcp_search",
            description=(
                "Search the enabled MCP servers for available tools. Use this "
                "when you need an external MCP capability or need the argument "
                "schema for a tool."
            ),
            args_schema=McpSearchInput,
        )
        call_tool = StructuredTool.from_function(
            coroutine=mcp_call,
            name="mcp_call",
            description=(
                "Call an MCP tool returned by mcp_search. Pass tool_name exactly "
                "as returned and provide arguments as a JSON object."
            ),
            args_schema=McpCallInput,
        )
        search_tool.handle_validation_error = lambda error: _mcp_error_result(
            tool_name="mcp_search",
            resolved_tool_name=None,
            error=error,
        )
        call_tool.handle_validation_error = lambda error: _mcp_error_result(
            tool_name="mcp_call",
            resolved_tool_name=None,
            error=error,
        )
        search_tool.handle_tool_error = lambda error: _mcp_error_result(
            tool_name="mcp_search",
            resolved_tool_name=None,
            error=error,
        )
        call_tool.handle_tool_error = lambda error: _mcp_error_result(
            tool_name="mcp_call",
            resolved_tool_name=None,
            error=error,
        )
        return [search_tool, call_tool]

    def search(
        self,
        *,
        query: str = "",
        server: str | None = None,
        limit: int = 10,
        include_schema: bool = False,
    ) -> str:
        limit = max(1, min(limit, _MAX_SEARCH_RESULTS))
        query_terms = _query_terms(query)
        server_filter = server.lower().strip() if server else None

        ranked: list[tuple[int, dict[str, Any]]] = []
        for info in self._tool_infos:
            if server_filter and info["server"].lower() != server_filter:
                continue
            score = self._score(info, query_terms)
            if query_terms and score <= 0:
                continue
            ranked.append((score, info))

        ranked.sort(
            key=lambda item: (
                -item[0],
                item[1]["server"].lower(),
                item[1]["name"].lower(),
            )
        )

        tools = [
            self._format_tool_info(info, include_schema=include_schema)
            for _, info in ranked[:limit]
        ]
        payload = {
            "tools": tools,
            "count": len(tools),
            "total_available": len(self._tool_infos),
        }
        if not tools:
            payload["hint"] = (
                "No matching MCP tools. Try a broader query or omit the server filter."
            )
        elif not include_schema:
            payload["hint"] = (
                "Call mcp_search with include_schema=true for the selected tool "
                "before mcp_call if you need exact arguments."
            )
        return json.dumps(payload, ensure_ascii=False)

    async def call(
        self,
        *,
        tool_name: str,
        arguments: dict[str, Any],
        callbacks: Any = None,
    ) -> str:
        resolved_name: str | None = None
        try:
            resolved_name = self._resolve_tool_name(tool_name)
            tool = self._tools_by_name[resolved_name]
            config = {"callbacks": callbacks} if callbacks is not None else None
            result = await tool.ainvoke(arguments or {}, config=config)
            return _trim_text(_serialize_result(result), _MAX_TOOL_OUTPUT_CHARS)
        except Exception as exc:
            if isinstance(exc, ValueError):
                logger.info("MCP tool call rejected: %s", _exception_message(exc))
            else:
                logger.warning(
                    "MCP tool call failed: %s",
                    _exception_message(exc),
                    exc_info=True,
                )
            return _mcp_error_result(
                tool_name=tool_name,
                resolved_tool_name=resolved_name,
                error=exc,
            )

    def _build_tool_info(self, tool: BaseTool) -> dict[str, Any]:
        server, original_name = _tool_identity(tool)
        return {
            "name": tool.name,
            "server": server,
            "tool": original_name,
            "description": _trim_text(tool.description or "", _MAX_DESCRIPTION_CHARS),
            "args": _compact_args(tool),
            "schema": _compact_schema(tool),
        }

    def _format_tool_info(
        self, info: dict[str, Any], *, include_schema: bool
    ) -> dict[str, Any]:
        payload = {
            "name": info["name"],
            "server": info["server"],
            "tool": info["tool"],
            "description": info["description"],
            "args": info["args"],
        }
        if include_schema:
            payload["schema"] = info["schema"]
        return payload

    def _score(self, info: dict[str, Any], query_terms: list[str]) -> int:
        if not query_terms:
            return 1
        haystack = " ".join(
            str(info[key]).lower()
            for key in ("name", "server", "tool", "description")
        )
        score = 0
        for term in query_terms:
            if term == info["tool"].lower() or term == info["name"].lower():
                score += 10
            elif term in info["tool"].lower():
                score += 6
            elif term in info["server"].lower():
                score += 4
            elif term in haystack:
                score += 2
        return score

    def _resolve_tool_name(self, tool_name: str) -> str:
        normalized = tool_name.strip()
        if normalized in self._tools_by_name:
            return normalized

        matches = []
        lowered = normalized.lower()
        for info in self._tool_infos:
            candidates = {
                info["tool"].lower(),
                f"{info['server']}.{info['tool']}".lower(),
                f"{info['server']}/{info['tool']}".lower(),
                info["name"].lower(),
            }
            if lowered in candidates:
                matches.append(info["name"])

        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            raise ValueError(
                "Ambiguous MCP tool name. Use the full name returned by mcp_search: "
                + ", ".join(sorted(matches))
            )
        raise ValueError(
            f"Unknown MCP tool '{tool_name}'. Use mcp_search to find an exact name."
        )


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
                    metadata = tool.metadata if isinstance(tool.metadata, dict) else {}
                    tool.metadata = {
                        **metadata,
                        "mcp_server": config.name,
                        "mcp_tool": original_name,
                    }
                    # Also update description if it's empty
                    if not tool.description:
                        tool.description = f"MCP tool {original_name} from server {config.name}"
                    
                    all_tools.append(tool)
                    
                logger.info(f"Successfully loaded {len(tools)} tools from MCP server: {config.name}")
            except Exception as e:
                logger.error(f"Failed to load MCP server {config.name}: {e}")
        return all_tools

    @staticmethod
    async def load_lazy_mcp_tools(
        server_configs: List[MCPServerConfig],
        exit_stack: AsyncExitStack,
    ) -> List[BaseTool]:
        tools = await McpService.load_mcp_tools(server_configs, exit_stack)
        if not tools:
            return []
        return McpToolRouter(tools).as_tools()


def _query_terms(query: str) -> list[str]:
    return [term.strip().lower() for term in query.split() if term.strip()]


def _tool_identity(tool: BaseTool) -> tuple[str, str]:
    metadata = tool.metadata if isinstance(tool.metadata, dict) else {}
    server = metadata.get("mcp_server")
    original_name = metadata.get("mcp_tool")
    if isinstance(server, str) and isinstance(original_name, str):
        return server, original_name

    name = tool.name
    if name.startswith(_MCP_TOOL_NAME_PREFIX):
        parts = name.split("__", 2)
        if len(parts) == 3:
            return parts[1], parts[2]
    return "unknown", name


def _compact_args(tool: BaseTool) -> dict[str, Any]:
    args = getattr(tool, "args", None)
    if not isinstance(args, dict):
        return {}
    compact: dict[str, Any] = {}
    for name, spec in args.items():
        if isinstance(spec, dict):
            compact[name] = {
                key: _trim_arg_value(spec[key])
                for key in ("type", "description", "default")
                if key in spec
            } or spec
        else:
            compact[name] = _trim_text(str(spec), _MAX_DESCRIPTION_CHARS)
    return compact


def _trim_arg_value(value: Any) -> Any:
    if isinstance(value, str):
        return _trim_text(value, _MAX_DESCRIPTION_CHARS)
    text = json.dumps(value, ensure_ascii=False, default=str)
    if len(text) <= _MAX_DESCRIPTION_CHARS:
        return value
    return {
        "truncated": True,
        "value": text[:_MAX_DESCRIPTION_CHARS],
    }


def _compact_schema(tool: BaseTool) -> Any:
    schema_source = getattr(tool, "tool_call_schema", None) or getattr(
        tool, "args_schema", None
    )
    if schema_source is None:
        return _compact_args(tool)
    if hasattr(schema_source, "model_json_schema"):
        schema = schema_source.model_json_schema()
    elif isinstance(schema_source, dict):
        schema = schema_source
    else:
        schema = _compact_args(tool)
    schema_text = json.dumps(schema, ensure_ascii=False, default=str)
    if len(schema_text) <= _MAX_SCHEMA_CHARS:
        return schema
    return {
        "truncated": True,
        "schema": schema_text[:_MAX_SCHEMA_CHARS],
    }


def _serialize_result(result: Any) -> str:
    if isinstance(result, str):
        return result
    try:
        return json.dumps(result, ensure_ascii=False, default=str)
    except TypeError:
        return str(result)


def _mcp_error_result(
    *,
    tool_name: str,
    resolved_tool_name: str | None,
    error: BaseException,
) -> str:
    payload = {
        "ok": False,
        "tool_name": tool_name,
        "resolved_tool_name": resolved_tool_name,
        "error": {
            "type": error.__class__.__name__,
            "message": _exception_message(error),
        },
        "hint": (
            "The MCP tool call failed. You can call mcp_search for the exact "
            "schema, correct the arguments, try another tool, or explain the "
            "failure if it is not recoverable."
        ),
    }
    return _trim_text(
        json.dumps(payload, ensure_ascii=False, default=str),
        _MAX_TOOL_OUTPUT_CHARS,
    )


def _exception_message(error: BaseException) -> str:
    if isinstance(error, BaseExceptionGroup):
        child_messages = [_exception_message(child) for child in error.exceptions]
        detail = "; ".join(message for message in child_messages if message)
        summary = str(error) or error.__class__.__name__
        if detail and detail not in summary:
            return f"{summary}: {detail}"
        return summary
    return str(error) or error.__class__.__name__


def _trim_text(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    omitted = len(value) - limit
    return f"{value[:limit]}\n...[truncated {omitted} chars]"
