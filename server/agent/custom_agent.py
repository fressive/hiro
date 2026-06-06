"""Session-scoped agent runner with persistence and token accounting."""

import asyncio
import json
from contextlib import AsyncExitStack, suppress
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, AsyncGenerator, Callable, TypedDict

from deepagents import create_deep_agent
from deepagents.backends import CompositeBackend, FilesystemBackend, StateBackend
from deepagents.middleware.subagents import GENERAL_PURPOSE_SUBAGENT
from langchain.chat_models import init_chat_model
from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langgraph.graph import END, START, StateGraph
from sqlalchemy import select

from server.agent.context import SessionContext
from server.agent.tool_call_ids import (
    ToolCallIdMiddleware,
    is_valid_tool_call_id,
    normalize_ai_message_tool_call_ids,
    normalize_model_messages,
)
from server.agent.tools import agent_tools
from server.core.logger import logger
from server.core.util import get_data_path
from server.db import AsyncSessionLocal
from server.models.models import AgentMessage, AgentSession, LLMConfig, MCPServerConfig
from server.models.schemas import AgentRunRequest
from server.service.mcp_service import McpService
from server.service.rag_service import RagService


def _format_sse(event: str, data: dict) -> str:
    payload = json.dumps(data, ensure_ascii=True)
    return f"event: {event}\ndata: {payload}\n\n"


def _tool_event_name(tool_name: str, phase: str) -> str:
    if tool_name.startswith("mcp__"):
        return f"mcp_{phase}"
    return f"tool_{phase}"


def _extract_message_text(message: Any) -> str:
    content = getattr(message, "content", None)
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return json.dumps(content)
    content_blocks = getattr(message, "content_blocks", None)
    if isinstance(content_blocks, list):
        return json.dumps(content_blocks)
    return ""


def _stream_text_segments(value: Any) -> list[tuple[str, str]]:
    """Extract visible text/thinking deltas from provider stream chunks."""
    if value is None:
        return []

    if isinstance(value, str):
        return [("text", value)] if value else []

    if isinstance(value, list):
        segments: list[tuple[str, str]] = []
        for item in value:
            segments.extend(_stream_text_segments(item))
        return segments

    if isinstance(value, dict):
        block_type = value.get("type")
        if block_type in {"thinking", "reasoning"}:
            text = (
                value.get("thinking")
                or value.get("reasoning")
                or value.get("text")
                or ""
            )
            return [("thinking", text)] if text else []

        if block_type in {"text", "text_delta"}:
            text = value.get("text") or ""
            return [("text", text)] if text else []

        if block_type in {"tool_use", "tool_call", "input_json_delta"}:
            return []

        text = value.get("text")
        return [("text", text)] if isinstance(text, str) and text else []

    content = getattr(value, "content", None)
    if content is not None:
        return _stream_text_segments(content)

    block_type = getattr(value, "type", None)
    if block_type in {"thinking", "reasoning"}:
        text = (
            getattr(value, "thinking", None)
            or getattr(value, "reasoning", None)
            or getattr(value, "text", None)
            or ""
        )
        return [("thinking", text)] if text else []

    if block_type in {"text", "text_delta"}:
        text = getattr(value, "text", "")
        return [("text", text)] if text else []

    return []


_TOKEN_USAGE_KEYS = ("input_tokens", "output_tokens", "cached_input_tokens")
_MAX_WRITEUP_CONTEXT_CHARS = 60000
_WRITEUP_INTENT_KEYWORDS = (
    "writeup",
    "write up",
    "report",
    "pentest report",
    "summary",
    "总结",
    "报告",
    "复盘",
)
_WRITEUP_SYSTEM_PROMPT = """You are a writeup subagent.

Generate a concise Markdown penetration-test report from the prior steps,
conversation, tool outputs, and final assistant result provided by the graph.

Requirements:
- Base the report only on provided evidence. Do not invent findings, flags, or exploitation results.
- Preserve important commands, URLs, payloads, tool outputs, and artifacts when they support a finding.
- If evidence is incomplete, say what is missing and mark the finding as unverified.
- Include these sections when applicable: Summary, Scope, Steps Performed, Findings, Evidence, Impact, Recommendations, Artifacts, and Next Steps.
- If a flag or proof value is present in the evidence, include it explicitly. If none is present, write "Flag: Not found".
- Return only the report Markdown, with no preamble."""
_GRAPH_NODES = [
    {
        "id": "persist_input",
        "label": "Persist Input",
        "description": "Save the user request and assistant placeholder.",
    },
    {
        "id": "prepare_context",
        "label": "Prepare Context",
        "description": "Load history, MCP tools, RAG context, and prompts.",
    },
    {
        "id": "execute_agent",
        "label": "Execute Agent",
        "description": "Run the selected agent with tools and skills.",
    },
    {
        "id": "writeup",
        "label": "Writeup",
        "description": "Generate a report from prior steps when requested.",
        "optional": True,
    },
    {
        "id": "persist_output",
        "label": "Persist Output",
        "description": "Save final messages and token usage.",
    },
]
_GRAPH_EDGES = [
    {"from": "persist_input", "to": "prepare_context"},
    {"from": "prepare_context", "to": "execute_agent"},
    {"from": "execute_agent", "to": "writeup", "condition": "report requested"},
    {"from": "execute_agent", "to": "persist_output", "condition": "default"},
    {"from": "writeup", "to": "persist_output"},
]


def _usage_value(data: Any, key: str) -> Any:
    if isinstance(data, dict):
        return data.get(key)
    return getattr(data, key, None)


def _token_count(value: Any) -> int:
    if isinstance(value, bool):
        return 0
    if isinstance(value, int):
        return max(value, 0)
    if isinstance(value, float):
        return max(int(value), 0)
    if isinstance(value, str):
        try:
            return max(int(value), 0)
        except ValueError:
            return 0
    return 0


def _first_token_count(data: Any, *keys: str) -> int:
    for key in keys:
        count = _token_count(_usage_value(data, key))
        if count:
            return count
    return 0


def _nested_token_count(data: Any, *path: str) -> int:
    current = data
    for key in path:
        current = _usage_value(current, key)
        if current is None:
            return 0
    return _token_count(current)


def _empty_token_usage() -> dict[str, int]:
    return {key: 0 for key in _TOKEN_USAGE_KEYS}


def _has_token_usage(usage: dict[str, int]) -> bool:
    return any(usage.get(key, 0) > 0 for key in _TOKEN_USAGE_KEYS)


def _add_token_usage(*usages: dict[str, int]) -> dict[str, int]:
    total = _empty_token_usage()
    for usage in usages:
        for key in _TOKEN_USAGE_KEYS:
            total[key] += usage.get(key, 0)
    return total


def _subtract_token_usage(
    usage: dict[str, int], subtract: dict[str, int]
) -> dict[str, int]:
    return {
        key: max((usage.get(key, 0) or 0) - (subtract.get(key, 0) or 0), 0)
        for key in _TOKEN_USAGE_KEYS
    }


def _normalize_token_usage(usage: Any) -> dict[str, int]:
    """Normalize token usage metadata from LangChain and provider-specific APIs."""
    normalized = _empty_token_usage()
    if not usage:
        return normalized

    input_tokens = _first_token_count(usage, "input_tokens", "prompt_tokens")
    output_tokens = _first_token_count(usage, "output_tokens", "completion_tokens")

    prompt_cache_hit_tokens = _first_token_count(
        usage, "prompt_cache_hit_tokens", "cache_read_input_tokens"
    )
    prompt_cache_miss_tokens = _first_token_count(usage, "prompt_cache_miss_tokens")
    if not input_tokens and (prompt_cache_hit_tokens or prompt_cache_miss_tokens):
        input_tokens = prompt_cache_hit_tokens + prompt_cache_miss_tokens

    total_tokens = _first_token_count(usage, "total_tokens")
    if total_tokens:
        if not input_tokens and output_tokens:
            input_tokens = max(total_tokens - output_tokens, 0)
        elif input_tokens and not output_tokens:
            output_tokens = max(total_tokens - input_tokens, 0)

    cached_input_tokens = _first_token_count(
        usage,
        "cached_input_tokens",
        "cache_read_input_tokens",
        "cache_read",
        "cached_tokens",
        "prompt_cache_hit_tokens",
    )
    if not cached_input_tokens:
        cached_input_tokens = (
            _nested_token_count(usage, "input_token_details", "cache_read")
            or _nested_token_count(usage, "input_token_details", "cached_tokens")
            or _nested_token_count(usage, "input_tokens_details", "cache_read")
            or _nested_token_count(usage, "input_tokens_details", "cached_tokens")
            or _nested_token_count(usage, "prompt_token_details", "cached_tokens")
            or _nested_token_count(usage, "prompt_tokens_details", "cached_tokens")
        )

    normalized["input_tokens"] = input_tokens
    normalized["output_tokens"] = output_tokens
    normalized["cached_input_tokens"] = cached_input_tokens
    return normalized


def _best_token_usage(candidates: list[Any]) -> dict[str, int]:
    best = _empty_token_usage()
    best_total = 0
    for candidate in candidates:
        usage = _normalize_token_usage(candidate)
        total = sum(usage.values())
        if total > best_total:
            best = usage
            best_total = total
    return best


def _metadata_usage_candidates(metadata: Any) -> list[Any]:
    if not metadata:
        return []
    return [
        _usage_value(metadata, "token_usage"),
        _usage_value(metadata, "usage"),
        _usage_value(metadata, "usage_metadata"),
    ]


def _message_token_usage(message: Any) -> dict[str, int]:
    response_metadata = getattr(message, "response_metadata", None)
    additional_kwargs = getattr(message, "additional_kwargs", None)
    candidates = [
        getattr(message, "usage_metadata", None),
        *_metadata_usage_candidates(response_metadata),
        *_metadata_usage_candidates(additional_kwargs),
    ]
    return _best_token_usage(candidates)


def _llm_result_token_usage(response: Any) -> dict[str, int]:
    if not response:
        return _empty_token_usage()

    llm_output = getattr(response, "llm_output", None)
    top_level_usage = _best_token_usage(
        [
            _usage_value(llm_output, "token_usage"),
            *_metadata_usage_candidates(_usage_value(llm_output, "metadata")),
            _usage_value(llm_output, "usage"),
            _usage_value(llm_output, "usage_metadata"),
        ]
    )

    generation_usages = []
    for generations in getattr(response, "generations", []) or []:
        for generation in generations:
            generation_usage = _best_token_usage(
                [
                    _message_token_usage(getattr(generation, "message", None)),
                    *_metadata_usage_candidates(
                        getattr(generation, "generation_info", None)
                    ),
                ]
            )
            if _has_token_usage(generation_usage):
                generation_usages.append(generation_usage)

    generation_usage = _add_token_usage(*generation_usages)
    if not _has_token_usage(top_level_usage):
        return generation_usage
    if not _has_token_usage(generation_usage):
        return top_level_usage
    return {
        key: max(top_level_usage.get(key, 0), generation_usage.get(key, 0))
        for key in _TOKEN_USAGE_KEYS
    }


def _apply_token_usage(message: AgentMessage, usage: dict[str, int]) -> None:
    if not _has_token_usage(usage):
        return
    message.input_tokens = usage["input_tokens"]
    message.output_tokens = usage["output_tokens"]
    message.cached_input_tokens = usage["cached_input_tokens"]


class _StreamCallbackHandler(BaseCallbackHandler):
    def __init__(self, queue: asyncio.Queue, loop: asyncio.AbstractEventLoop):
        self._queue = queue
        self._loop = loop
        self._tool_names: list[str] = []
        self._mcp_names: list[str] = []
        self._tool_run_map: dict[str, str] = {}
        self._token_buffer: list[str] = []
        self._usage: dict[str, int] = _empty_token_usage()

    @property
    def tool_names(self) -> list[str]:
        return self._tool_names

    @property
    def mcp_names(self) -> list[str]:
        return self._mcp_names

    @property
    def usage(self) -> dict[str, int]:
        return self._usage

    def _enqueue(self, event: str, data: dict) -> None:
        asyncio.run_coroutine_threadsafe(
            self._queue.put(_format_sse(event, data)), self._loop
        )

    def on_llm_new_token(self, token: Any, **kwargs: Any) -> None:
        segments = _stream_text_segments(token)
        if not segments:
            chunk = kwargs.get("chunk")
            message = getattr(chunk, "message", None)
            segments = _stream_text_segments(message)

        for segment_type, text in segments:
            self._token_buffer.append(text)
            self._enqueue("token", {"text": text, "type": segment_type})

    @property
    def token_text(self) -> str:
        return "".join(self._token_buffer)

    def on_llm_end(self, response: Any, **kwargs: Any) -> None:
        usage = _llm_result_token_usage(response)
        if not _has_token_usage(usage):
            return

        self._usage = _add_token_usage(self._usage, usage)

    def on_tool_start(self, serialized: dict, input_str: str, **kwargs: Any) -> None:
        tool_name = serialized.get("name") or "tool"
        if tool_name.startswith("mcp__"):
            self._mcp_names.append(tool_name)
        else:
            self._tool_names.append(tool_name)

        run_id = str(kwargs.get("run_id", ""))
        if run_id:
            self._tool_run_map[run_id] = tool_name
        self._enqueue(
            _tool_event_name(tool_name, "start"),
            {"id": run_id, "name": tool_name, "input": str(input_str)},
        )

    def on_tool_end(self, output: Any, **kwargs: Any) -> None:
        run_id = str(kwargs.get("run_id", ""))
        tool_name = self._tool_run_map.get(run_id, "tool")
        self._enqueue(
            _tool_event_name(tool_name, "end"),
            {"id": run_id, "name": tool_name, "output": str(output)},
        )


@dataclass
class _AgentRunContext:
    queue: asyncio.Queue[str | None]
    callback: _StreamCallbackHandler
    agent_done: asyncio.Event
    exit_stack: AsyncExitStack
    update_task: asyncio.Task | None = None
    assistant_msg_id: int | None = None
    user_msg_id: int | None = None
    mcp_tools: list[Any] = field(default_factory=list)
    history_messages: list[BaseMessage] = field(default_factory=list)
    full_system_prompt: str = ""
    all_messages: list[Any] = field(default_factory=list)
    assistant_text: str = ""
    writeup_text: str = ""


class _AgentGraphState(TypedDict):
    run: _AgentRunContext


class CustomAgent:
    """Run a configured agent for one application session and persist its history."""

    def __init__(
        self,
        *,
        session_id: int,
        session_title: str | None,
        payload: AgentRunRequest,
        config: LLMConfig,
    ) -> None:
        self.session_id = session_id
        self.session_title = session_title
        self.payload = payload
        self.config = config
        self.input_text = payload.input.strip()
        self.rag_context = ""
        self.rag_sources: list[str] = []
        self._rag_loaded = False
        self._execution_graph = self._build_execution_graph()

    async def stream(
        self,
        *,
        on_task_started: Callable[[asyncio.Task], None] | None = None,
        on_task_done: Callable[[], None] | None = None,
    ) -> AsyncGenerator[str, None]:
        await self._load_rag_context()

        queue: asyncio.Queue[str | None] = asyncio.Queue()
        loop = asyncio.get_running_loop()
        callback = _StreamCallbackHandler(queue, loop)

        await queue.put(
            _format_sse(
                "session",
                {"id": self.session_id, "title": self.session_title},
            )
        )

        if self.rag_sources:
            await queue.put(_format_sse("rag_search", {"sources": self.rag_sources}))

        await queue.put(
            _format_sse(
                "graph_init",
                {
                    "nodes": _GRAPH_NODES,
                    "edges": _GRAPH_EDGES,
                },
            )
        )

        task = asyncio.create_task(self._run_agent(queue, callback, on_task_done))
        if on_task_started:
            on_task_started(task)

        try:
            while True:
                message = await queue.get()
                if message is None:
                    break
                yield message
        finally:
            logger.info(
                "Client disconnected for session %s. Agent task continues in background.",
                self.session_id,
            )

    async def _run_agent(
        self,
        queue: asyncio.Queue[str | None],
        callback: _StreamCallbackHandler,
        on_task_done: Callable[[], None] | None,
    ) -> None:
        run_context: _AgentRunContext | None = None
        try:
            async with AsyncExitStack() as exit_stack:
                run_context = _AgentRunContext(
                    queue=queue,
                    callback=callback,
                    agent_done=asyncio.Event(),
                    exit_stack=exit_stack,
                )
                await self._execution_graph.ainvoke({"run": run_context})

        except Exception as exc:
            logger.error("Agent execution error: %s", exc)
            assistant_msg_id = (
                run_context.assistant_msg_id if run_context is not None else None
            )
            await self._write_error_message(exc, assistant_msg_id)
            await queue.put(
                _format_sse(
                    "error",
                    {"message": str(exc), "session_id": self.session_id},
                )
            )
        finally:
            if run_context is not None:
                run_context.agent_done.set()
            update_task = run_context.update_task if run_context is not None else None
            if update_task and not update_task.done():
                update_task.cancel()
                with suppress(asyncio.CancelledError):
                    await update_task
            if on_task_done:
                on_task_done()
            await queue.put(None)

    def _build_execution_graph(self) -> Any:
        graph = StateGraph(_AgentGraphState)
        graph.add_node("persist_input", self._graph_persist_input)
        graph.add_node("prepare_context", self._graph_prepare_context)
        graph.add_node("execute_agent", self._graph_execute_agent)
        graph.add_node("writeup", self._graph_writeup)
        graph.add_node("persist_output", self._graph_persist_output)
        graph.add_edge(START, "persist_input")
        graph.add_edge("persist_input", "prepare_context")
        graph.add_edge("prepare_context", "execute_agent")
        graph.add_conditional_edges(
            "execute_agent",
            self._route_after_execute,
            {
                "writeup": "writeup",
                "persist_output": "persist_output",
            },
        )
        graph.add_edge("writeup", "persist_output")
        graph.add_edge("persist_output", END)
        return graph.compile()

    def _route_after_execute(self, state: _AgentGraphState) -> str:
        if self._should_generate_writeup():
            return "writeup"
        self._enqueue_graph_node(state["run"], "writeup", "skipped")
        return "persist_output"

    async def _graph_persist_input(
        self, state: _AgentGraphState
    ) -> _AgentGraphState:
        run = state["run"]
        await self._emit_graph_node(run, "persist_input", "running")
        try:
            run.user_msg_id = await self._save_user_message()
            run.assistant_msg_id = await self._create_assistant_placeholder()
            run.update_task = asyncio.create_task(
                self._update_assistant_periodically(
                    run.assistant_msg_id,
                    run.callback,
                    run.agent_done,
                )
            )
        except Exception:
            await self._emit_graph_node(run, "persist_input", "error")
            raise
        await self._emit_graph_node(run, "persist_input", "done")
        return {"run": run}

    async def _graph_prepare_context(
        self, state: _AgentGraphState
    ) -> _AgentGraphState:
        run = state["run"]
        await self._emit_graph_node(run, "prepare_context", "running")
        if run.user_msg_id is None or run.assistant_msg_id is None:
            await self._emit_graph_node(run, "prepare_context", "error")
            raise RuntimeError("Agent history persistence was not initialized")

        try:
            run.mcp_tools = await self._load_mcp_tools(run.exit_stack)
            run.history_messages = await self._load_history(
                user_msg_id=run.user_msg_id,
                assistant_msg_id=run.assistant_msg_id,
            )
            run.full_system_prompt = self._build_system_prompt(run.mcp_tools)
        except Exception:
            await self._emit_graph_node(run, "prepare_context", "error")
            raise
        await self._emit_graph_node(run, "prepare_context", "done")
        return {"run": run}

    async def _graph_execute_agent(
        self, state: _AgentGraphState
    ) -> _AgentGraphState:
        run = state["run"]
        await self._emit_graph_node(run, "execute_agent", "running")
        try:
            run.all_messages = await self._execute(
                history_messages=run.history_messages,
                mcp_tools=run.mcp_tools,
                full_system_prompt=run.full_system_prompt,
                callback=run.callback,
            )
        except Exception:
            await self._emit_graph_node(run, "execute_agent", "error")
            raise
        await self._emit_graph_node(run, "execute_agent", "done")
        return {"run": run}

    async def _graph_writeup(self, state: _AgentGraphState) -> _AgentGraphState:
        run = state["run"]
        await self._emit_graph_node(run, "writeup", "running")
        try:
            writeup_message = await self._generate_writeup(run)
            run.writeup_text = _extract_message_text(writeup_message)
            if run.writeup_text:
                await self._save_writeup_artifact(run.writeup_text)
            run.all_messages.append(writeup_message)
        except Exception:
            await self._emit_graph_node(run, "writeup", "error")
            raise
        await self._emit_graph_node(run, "writeup", "done")
        return {"run": run}

    async def _graph_persist_output(
        self, state: _AgentGraphState
    ) -> _AgentGraphState:
        run = state["run"]
        await self._emit_graph_node(run, "persist_output", "running")
        if run.assistant_msg_id is None:
            await self._emit_graph_node(run, "persist_output", "error")
            raise RuntimeError("Assistant placeholder was not initialized")

        try:
            run.agent_done.set()
            if run.update_task is not None:
                await run.update_task
                run.update_task = None

            new_messages = [
                normalize_ai_message_tool_call_ids(msg)
                if isinstance(msg, BaseMessage)
                else msg
                for msg in run.all_messages[len(run.history_messages) + 1 :]
            ]
            run.assistant_text = await self._save_final_messages(
                new_messages=new_messages,
                assistant_msg_id=run.assistant_msg_id,
                callback_usage=run.callback.usage,
                callback_text=run.callback.token_text,
            )
            if run.writeup_text:
                run.assistant_text = run.writeup_text
            elif not run.assistant_text:
                run.assistant_text = run.callback.token_text

            await self._emit_graph_node(run, "persist_output", "done")
            await run.queue.put(
                _format_sse(
                    "done",
                    {"text": run.assistant_text, "session_id": self.session_id},
                )
            )
        except Exception:
            await self._emit_graph_node(run, "persist_output", "error")
            raise
        return {"run": run}

    async def _emit_graph_node(
        self,
        run: _AgentRunContext,
        node_id: str,
        status: str,
    ) -> None:
        await run.queue.put(self._graph_node_event(node_id, status))

    def _enqueue_graph_node(
        self,
        run: _AgentRunContext,
        node_id: str,
        status: str,
    ) -> None:
        run.queue.put_nowait(self._graph_node_event(node_id, status))

    def _graph_node_event(self, node_id: str, status: str) -> str:
        return _format_sse(
            "graph_node",
            {
                "id": node_id,
                "status": status,
            },
        )

    def _should_generate_writeup(self) -> bool:
        user_input = self.input_text.lower()
        return any(keyword in user_input for keyword in _WRITEUP_INTENT_KEYWORDS)

    async def _generate_writeup(self, run: _AgentRunContext) -> AIMessage:
        report_context = self._build_writeup_context(run)
        result = await self._build_llm().ainvoke(
            [
                SystemMessage(content=_WRITEUP_SYSTEM_PROMPT),
                HumanMessage(content=report_context),
            ],
            config={"callbacks": [run.callback]},
        )
        result_messages = result if isinstance(result, list) else [result]
        normalized_messages = normalize_model_messages(result_messages)
        for message in reversed(normalized_messages):
            if isinstance(message, AIMessage):
                return message
        return AIMessage(content="\n\n".join(_extract_message_text(m) for m in result_messages))

    def _build_writeup_context(self, run: _AgentRunContext) -> str:
        messages = run.all_messages or (
            run.history_messages + [HumanMessage(content=self.input_text)]
        )
        rendered_messages = [
            rendered
            for message in messages
            if (rendered := self._format_message_for_writeup(message))
        ]
        context = "\n\n".join(
            [
                f"Session ID: {self.session_id}",
                f"Generated at: {datetime.now(timezone.utc).isoformat()}",
                f"Current user request: {self.input_text}",
                "Prior steps, tool outputs, and assistant results:",
                *rendered_messages,
            ]
        )
        if len(context) <= _MAX_WRITEUP_CONTEXT_CHARS:
            return context
        return (
            "The oldest context was truncated to fit the writeup window.\n\n"
            + context[-_MAX_WRITEUP_CONTEXT_CHARS:]
        )

    def _format_message_for_writeup(self, message: Any) -> str:
        label = self._message_role_label(message)
        parts: list[str] = []
        content = _extract_message_text(message)
        if content:
            parts.append(content)

        tool_calls = getattr(message, "tool_calls", None)
        if tool_calls:
            parts.append(
                "Tool calls: "
                + json.dumps(tool_calls, ensure_ascii=True, default=str)
            )

        if not parts:
            return ""
        return f"### {label}\n" + "\n".join(parts)

    def _message_role_label(self, message: Any) -> str:
        if isinstance(message, HumanMessage):
            return "User"
        if isinstance(message, AIMessage):
            return "Assistant"
        if isinstance(message, ToolMessage):
            name = getattr(message, "name", None) or "tool"
            return f"Tool: {name}"
        message_type = getattr(message, "type", None)
        if message_type:
            return str(message_type).title()
        return type(message).__name__

    async def _save_writeup_artifact(self, report_markdown: str) -> None:
        data_path = get_data_path(self.session_id) / "data"
        data_path.mkdir(parents=True, exist_ok=True)
        (data_path / "WRITEUP.md").write_text(report_markdown, encoding="utf-8")

    async def _load_rag_context(self) -> None:
        if self._rag_loaded or not self.payload.enable_rag:
            self._rag_loaded = True
            return

        try:
            hits = await RagService.search(self.input_text, limit=5)
            if hits:
                context_parts = []
                for hit in hits:
                    source = hit.get("title", "Unknown")
                    text = hit.get("text", "")
                    context_parts.append(f"--- Source: {source} ---\n{text}")
                    if source not in self.rag_sources:
                        self.rag_sources.append(source)
                self.rag_context = "\n\n".join(context_parts)
        except Exception as exc:
            logger.warning(
                "RAG retrieval failed for session %s: %s",
                self.session_id,
                exc,
            )
        finally:
            self._rag_loaded = True

    async def _save_user_message(self) -> int:
        async with AsyncSessionLocal() as db_session:
            user_message = AgentMessage(
                session_id=self.session_id,
                role="user",
                content=self.input_text,
                created_at=datetime.now(timezone.utc),
            )
            db_session.add(user_message)

            sess_result = await db_session.execute(
                select(AgentSession).where(AgentSession.id == self.session_id)
            )
            db_sess = sess_result.scalars().first()
            if db_sess:
                db_sess.updated_at = datetime.now(timezone.utc)
                if not db_sess.title:
                    db_sess.title = self.input_text[:80]

            await db_session.commit()
            await db_session.refresh(user_message)
            return user_message.id

    async def _create_assistant_placeholder(self) -> int:
        async with AsyncSessionLocal() as db_session:
            assistant_message = AgentMessage(
                session_id=self.session_id,
                role="assistant",
                content="",
                model=self.config.model,
                created_at=datetime.now(timezone.utc),
            )
            db_session.add(assistant_message)
            await db_session.commit()
            await db_session.refresh(assistant_message)
            return assistant_message.id

    async def _update_assistant_periodically(
        self,
        assistant_msg_id: int,
        callback: _StreamCallbackHandler,
        agent_done: asyncio.Event,
    ) -> None:
        last_saved = ""
        while not agent_done.is_set():
            try:
                await asyncio.wait_for(agent_done.wait(), timeout=2)
                break
            except asyncio.TimeoutError:
                current = callback.token_text
                if current == last_saved:
                    continue
                async with AsyncSessionLocal() as db_session:
                    msg = await db_session.get(AgentMessage, assistant_msg_id)
                    if msg:
                        msg.content = current
                        await db_session.commit()
                        last_saved = current
            except Exception as exc:
                logger.error("Error in periodic assistant update: %s", exc)

    async def _load_mcp_tools(self, exit_stack: AsyncExitStack) -> list[Any]:
        if not self.payload.mcp_servers:
            return []

        logger.info("Loading tools from MCP servers: %s", self.payload.mcp_servers)
        async with AsyncSessionLocal() as db_session:
            mcp_configs_result = await db_session.execute(
                select(MCPServerConfig).where(
                    MCPServerConfig.name.in_(self.payload.mcp_servers)
                )
            )
            found_configs = mcp_configs_result.scalars().all()

        if not found_configs:
            return []
        return await McpService.load_mcp_tools(found_configs, exit_stack)

    async def _load_history(
        self, *, user_msg_id: int, assistant_msg_id: int
    ) -> list[BaseMessage]:
        history_messages: list[BaseMessage] = []
        pending_tool_calls: list[dict[str, str | None]] = []

        async with AsyncSessionLocal() as db_session:
            result = await db_session.execute(
                select(AgentMessage)
                .where(AgentMessage.session_id == self.session_id)
                .order_by(AgentMessage.created_at.asc())
            )
            db_messages = result.scalars().all()

        for message in db_messages:
            if message.id in {user_msg_id, assistant_msg_id}:
                continue

            if message.role == "assistant":
                if not message.content and not message.tool_calls:
                    continue
                ai_message = normalize_ai_message_tool_call_ids(
                    AIMessage(
                        content=message.content,
                        tool_calls=message.tool_calls or [],
                    )
                )
                history_messages.append(ai_message)
                for tool_call in getattr(ai_message, "tool_calls", []):
                    tool_call_id = tool_call.get("id")
                    if is_valid_tool_call_id(tool_call_id):
                        pending_tool_calls.append(
                            {"id": tool_call_id, "name": tool_call.get("name")}
                        )
            elif message.role == "tool":
                tool_message = self._build_history_tool_message(
                    message, pending_tool_calls
                )
                if tool_message:
                    history_messages.append(tool_message)
            else:
                history_messages.append(HumanMessage(content=message.content))

        for tool_call in pending_tool_calls:
            history_messages.append(
                ToolMessage(
                    content=(
                        "Tool call "
                        f"{tool_call['name'] or 'unknown'} was cancelled before "
                        "a result was saved."
                    ),
                    tool_call_id=tool_call["id"],
                    name=tool_call["name"],
                    status="error",
                )
            )

        return history_messages

    def _build_history_tool_message(
        self,
        message: AgentMessage,
        pending_tool_calls: list[dict[str, str | None]],
    ) -> ToolMessage | None:
        tcid = message.tool_call_id
        if not is_valid_tool_call_id(tcid):
            matching_indexes = [
                index
                for index, tool_call in enumerate(pending_tool_calls)
                if tool_call["name"] == message.name
            ]
            if len(matching_indexes) == 1:
                tcid = pending_tool_calls.pop(matching_indexes[0])["id"]
            elif len(pending_tool_calls) == 1:
                tcid = pending_tool_calls.pop(0)["id"]
            else:
                logger.warning(
                    "Skipping tool message %s with missing tool_call_id",
                    message.id,
                )
                return None
        else:
            matching_index = next(
                (
                    index
                    for index, tool_call in enumerate(pending_tool_calls)
                    if tool_call["id"] == tcid
                ),
                None,
            )
            if matching_index is None:
                logger.warning(
                    "Skipping orphan tool message %s with tool_call_id %s",
                    message.id,
                    tcid,
                )
                return None
            pending_tool_calls.pop(matching_index)

        return ToolMessage(
            content=message.content,
            tool_call_id=tcid,
            name=message.name,
        )

    def _build_system_prompt(self, mcp_tools: list[Any]) -> str:
        full_system_prompt = self.payload.system_prompt or ""
        if mcp_tools:
            mcp_tools_info = "\n".join(
                f"- {tool.name}: {tool.description}" for tool in mcp_tools
            )
            full_system_prompt += (
                "\n\nYou have access to the following MCP tools:\n"
                f"{mcp_tools_info}"
            )
        if self.rag_context:
            full_system_prompt += (
                "\n\nRELEVANT CONTEXT FROM DOCUMENTS:\n"
                f"{self.rag_context}"
            )
        return full_system_prompt

    async def _execute(
        self,
        *,
        history_messages: list[BaseMessage],
        mcp_tools: list[Any],
        full_system_prompt: str,
        callback: _StreamCallbackHandler,
    ) -> list[Any]:
        llm = self._build_llm()
        current_tools = self._selected_builtin_tools() + mcp_tools

        if self.payload.is_deep_agent:
            skills_sources = ["./skills"]
            agent = create_deep_agent(
                llm,
                tools=current_tools,
                context_schema=SessionContext,
                backend=self._build_backend(),
                skills=skills_sources,
                system_prompt=full_system_prompt,
                middleware=[ToolCallIdMiddleware()],
                subagents=[
                    {
                        **GENERAL_PURPOSE_SUBAGENT,
                        "skills": skills_sources,
                        "middleware": [ToolCallIdMiddleware()],
                    }
                ],
            )
            result_state = await agent.ainvoke(
                {
                    "messages": history_messages
                    + [HumanMessage(content=self.input_text)]
                },
                config={"callbacks": [callback]},
                context=SessionContext(self.session_id),
            )
            return result_state.get("messages", [])

        llm_messages: list[BaseMessage] = []
        if full_system_prompt:
            llm_messages.append(SystemMessage(content=full_system_prompt))
        llm_messages.extend(history_messages)
        llm_messages.append(HumanMessage(content=self.input_text))
        llm_with_tools = llm.bind_tools(current_tools) if current_tools else llm
        result_payload = await llm_with_tools.ainvoke(
            llm_messages,
            config={"callbacks": [callback]},
        )
        result_messages = (
            result_payload if isinstance(result_payload, list) else [result_payload]
        )
        return (
            history_messages
            + [HumanMessage(content=self.input_text)]
            + normalize_model_messages(result_messages)
        )

    def _build_llm(self) -> Any:
        provider = self.config.provider.lower()
        model_name = self.config.model.lower()
        if model_name.startswith("claude") or "anthropic" in model_name:
            provider = "anthropic"

        base_url = self.config.base_url
        if provider == "anthropic" and base_url and base_url.endswith("/v1"):
            base_url = base_url.rsplit("/v1", 1)[0]

        model_kwargs: dict[str, Any] = {}
        if self.config.enable_1m_context:
            if provider == "openai":
                model_kwargs["enable_1m_context"] = True
            elif provider == "anthropic":
                model_kwargs["betas"] = ["context-1m-2025-08-07"]

        init_kwargs: dict[str, Any] = {
            "model": self.config.model,
            "model_provider": provider,
            "api_key": self.config.api_key,
            "base_url": base_url,
            "streaming": True,
            "max_retries": 5,
        }

        if self.payload.temperature is not None:
            init_kwargs["temperature"] = self.payload.temperature
        if self.payload.max_tokens is not None:
            init_kwargs["max_tokens"] = self.payload.max_tokens

        return init_chat_model(**init_kwargs, **model_kwargs)

    def _selected_builtin_tools(self) -> list[Any]:
        if self.payload.tools is None:
            return []
        return [tool for tool in agent_tools if tool.name in self.payload.tools]

    def _build_backend(self) -> CompositeBackend:
        data_path = get_data_path(self.session_id)
        return CompositeBackend(
            default=StateBackend(),
            routes={
                f"{str(data_path.absolute())}/": FilesystemBackend(
                    data_path,
                    virtual_mode=True,
                    max_file_size_mb=1000,
                )
            },
        )

    async def _save_final_messages(
        self,
        *,
        new_messages: list[Any],
        assistant_msg_id: int,
        callback_usage: Any,
        callback_text: str,
    ) -> str:
        assistant_text = ""
        message_usages = {
            index: _message_token_usage(msg)
            for index, msg in enumerate(new_messages)
            if isinstance(msg, AIMessage)
        }
        normalized_callback_usage = _normalize_token_usage(callback_usage)
        residual_usage = _subtract_token_usage(
            normalized_callback_usage,
            _add_token_usage(*message_usages.values()),
        )
        residual_applied = False
        placeholder_updated = False

        async with AsyncSessionLocal() as db_session:
            for index, msg in enumerate(new_messages):
                role = "user"
                content = _extract_message_text(msg)
                usage = _empty_token_usage()

                if isinstance(msg, AIMessage):
                    role = "assistant"
                    if not assistant_text and not msg.tool_calls:
                        assistant_text = content

                    usage = message_usages.get(index, _empty_token_usage())
                    if not residual_applied and _has_token_usage(residual_usage):
                        usage = _add_token_usage(usage, residual_usage)
                        residual_applied = True

                    if not placeholder_updated:
                        msg_to_update = await db_session.get(
                            AgentMessage, assistant_msg_id
                        )
                        if msg_to_update:
                            msg_to_update.content = content
                            msg_to_update.tool_calls = msg.tool_calls
                            msg_to_update.model = self.config.model
                            _apply_token_usage(msg_to_update, usage)
                            placeholder_updated = True
                            continue

                elif isinstance(msg, ToolMessage):
                    role = "tool"
                elif isinstance(msg, HumanMessage):
                    role = "user"

                db_msg = AgentMessage(
                    session_id=self.session_id,
                    role=role,
                    content=content,
                    name=getattr(msg, "name", None),
                    tool_call_id=getattr(msg, "tool_call_id", None),
                    tool_calls=getattr(msg, "tool_calls", None),
                    model=self.config.model if role == "assistant" else None,
                    created_at=datetime.now(timezone.utc),
                )

                if isinstance(msg, AIMessage):
                    _apply_token_usage(db_msg, usage)

                db_session.add(db_msg)

            if not placeholder_updated and (
                callback_text or _has_token_usage(normalized_callback_usage)
            ):
                msg_to_update = await db_session.get(AgentMessage, assistant_msg_id)
                if msg_to_update:
                    msg_to_update.content = callback_text
                    msg_to_update.model = self.config.model
                    _apply_token_usage(msg_to_update, normalized_callback_usage)

            await db_session.commit()

        return assistant_text

    async def _write_error_message(
        self, exc: Exception, assistant_msg_id: int | None
    ) -> None:
        async with AsyncSessionLocal() as db_session:
            if assistant_msg_id is not None:
                msg = await db_session.get(AgentMessage, assistant_msg_id)
                if msg:
                    msg.content = f"Error: {exc}"
                    msg.model = self.config.model
                    await db_session.commit()
                    return

            db_session.add(
                AgentMessage(
                    session_id=self.session_id,
                    role="assistant",
                    content=f"Error: {exc}",
                    model=self.config.model,
                    created_at=datetime.now(timezone.utc),
                )
            )
            await db_session.commit()
