"""LLM construction and execution for session-scoped agents."""

import asyncio
import inspect
import json
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from deepagents import create_deep_agent
from deepagents.backends import CompositeBackend, FilesystemBackend
from deepagents.middleware.subagents import GENERAL_PURPOSE_SUBAGENT
from langchain.chat_models import init_chat_model
from langchain_core.messages import BaseMessage, HumanMessage

from server.agent.events.streaming import StreamCallbackHandler
from server.agent.runtime.context import SessionContext
from server.agent.runtime.mcp_loader import create_dynamic_mcp_router_tools
from server.agent.runtime.sandboxed_backend import SessionSandboxedBackend
from server.agent.subagents import (
    SubAgent,
    load_subagent_classes,
)
from server.agent.tools import agent_tools
from server.agent.utils.tool_call_ids import ToolCallIdMiddleware
from server.core.logger import logger
from server.core.util import get_data_path
from server.models.llm import LLMConfig
from server.schemas.agent import AgentRunRequest

SYSTEM_PROMPT = """"""
SKILLS_ROOT = Path("./skills")
MAIN_AGENT_SKILL_SOURCE_DIRS = ("main-agent", "exploit-agent")
MAX_STREAMING_ATTEMPTS = 2
STREAM_RETRY_BACKOFF_SECONDS = 0.5
RETRYABLE_STREAM_ERROR_MARKERS = (
    "empty_stream",
    "error code: 408",
    "stream error",
    "stream disconnected before completion",
    "stream closed before response.completed",
    "upstream stream closed before first payload",
    "response.completed",
    "remoteprotocolerror",
    "incompleteread",
    "no streaming chunk received",
)

SUBAGENT_DELEGATION_PROMPT = """## DeepAgent Subagent Delegation

Specialized DeepAgent subagents are available through the `task` tool.
Use them when their focused role fits the user's request or the current
penetration-testing workflow.

Available specialized subagents:
{subagent_descriptions}

Delegation guidance:
{subagent_delegation_rules}
- The calling agent only receives the subagent's final result. After a subagent
  returns, synthesize or present that result to the user as needed."""


def is_retryable_stream_error(error: BaseException) -> bool:
    """Return whether an exception represents a transient stream disconnect."""

    if isinstance(error, BaseExceptionGroup):
        return any(is_retryable_stream_error(child) for child in error.exceptions)

    status_code = getattr(error, "status_code", None)
    if status_code == 408:
        return True

    message = str(error).lower()
    return any(marker in message for marker in RETRYABLE_STREAM_ERROR_MARKERS)


class AgentRuntime:
    """Build and hold the session-scoped DeepAgent runtime.

    This class deliberately does not own persistence or streaming queue
    lifetime. It keeps the main agent reference stable for the session while
    accepting per-run input, callback, and context updates.
    """

    def __init__(
        self,
        *,
        session_id: int,
        input_text: str,
        payload: AgentRunRequest,
        config: LLMConfig,
        agent_configs: dict[str, LLMConfig] | None = None,
    ) -> None:
        self.session_id = session_id
        self.input_text = input_text
        self.payload = payload
        self.config = config
        self.agent_configs = agent_configs or {}
        self._main_agent: Any | None = None
        self._fallback_agent: Any | None = None
        self._mcp_router_tools_by_agent: dict[str, list[Any]] = {}
        self._agent_model_names: dict[str, str] | None = None

    def configure_run(
        self,
        *,
        input_text: str,
        payload: AgentRunRequest,
        config: LLMConfig,
        agent_configs: dict[str, LLMConfig] | None = None,
    ) -> None:
        """Update per-run inputs while keeping the session agent references."""

        self.input_text = input_text
        self.payload = payload
        self.config = config
        self.agent_configs = agent_configs or {}

    def build_system_prompt(self) -> str:
        """Build static instructions used when the session main agent is created."""

        full_system_prompt = self.payload.system_prompt or SYSTEM_PROMPT
        # MCP tools are stable router tools on each agent. They read the
        # current run's MCP server list when called instead of binding to one
        # run's MCP sessions.
        full_system_prompt += (
            "\n\nMCP access, when configured for the current agent, is "
            "available through two router tools: use mcp_search to find "
            "available MCP tools and schemas, then use mcp_call with the exact "
            "tool_name and JSON arguments. The main agent and each subagent may "
            "have different MCP servers."
        )
        return full_system_prompt

    def build_run_context_prompt(self, *, rag_context: str) -> str:
        """Build dynamic context that belongs only to the current user turn."""

        if not rag_context:
            return ""
        return "RELEVANT CONTEXT FROM DOCUMENTS:\n" f"{rag_context}"

    def build_main_agent_prompt(self, full_system_prompt: str) -> str:
        """Append project-specific subagent delegation rules for DeepAgent."""

        subagent_classes = self.specialized_subagent_classes()
        if not subagent_classes:
            return full_system_prompt

        descriptions = "\n".join(
            f"- `{subagent_class.name}`: {subagent_class.description}"
            for subagent_class in subagent_classes
        )
        delegation_rules = "\n".join(
            f"- {_delegation_rule(subagent_class)}"
            for subagent_class in subagent_classes
        )
        section = SUBAGENT_DELEGATION_PROMPT.format(
            subagent_descriptions=descriptions,
            subagent_delegation_rules=delegation_rules,
        )
        if not full_system_prompt.strip():
            return section
        return f"{full_system_prompt}\n\n{section}"

    async def execute(
        self,
        *,
        history_messages: list[BaseMessage],
        full_system_prompt: str,
        run_context_prompt: str,
        callback: StreamCallbackHandler | None,
    ) -> list[Any]:
        """Run the main agent and return the complete message sequence."""

        main_system_prompt = self.build_main_agent_prompt(full_system_prompt)

        for attempt in range(1, MAX_STREAMING_ATTEMPTS + 2):
            streaming = attempt <= MAX_STREAMING_ATTEMPTS
            checkpoint_id = f"execute-agent-{attempt}"
            snapshot = callback.snapshot() if callback is not None else None
            if callback is not None:
                callback.emit_event("live_checkpoint", {"id": checkpoint_id})

            try:
                messages = await self._execute_deep_agent(
                    main_system_prompt=main_system_prompt,
                    run_context_prompt=run_context_prompt,
                    callback=callback,
                    history_messages=history_messages,
                    streaming=streaming,
                )
                if callback is not None:
                    callback.emit_event("live_commit", {"id": checkpoint_id})
                return messages
            except Exception as exc:
                if not streaming or not is_retryable_stream_error(exc):
                    if callback is not None:
                        callback.emit_event("live_commit", {"id": checkpoint_id})
                    raise

                if callback is not None and snapshot is not None:
                    callback.rollback(snapshot)
                    callback.emit_event(
                        "live_rollback",
                        {
                            "id": checkpoint_id,
                            "attempt": attempt,
                            "retrying": True,
                            "fallback": attempt == MAX_STREAMING_ATTEMPTS,
                            "message": "Stream disconnected; retrying the model call.",
                        },
                    )
                logger.warning(
                    "Retryable stream error in session %s on attempt %s: %s",
                    self.session_id,
                    attempt,
                    exc,
                )
                await asyncio.sleep(STREAM_RETRY_BACKOFF_SECONDS * attempt)

        raise RuntimeError("Agent execution retry loop exited unexpectedly")

    async def _execute_deep_agent(
        self,
        *,
        main_system_prompt: str,
        run_context_prompt: str,
        callback: StreamCallbackHandler | None,
        history_messages: list[BaseMessage],
        streaming: bool,
    ) -> list[Any]:
        """Execute one DeepAgent attempt."""

        agent = self.main_agent(
            streaming=streaming,
            main_system_prompt=main_system_prompt,
        )
        input_content = self.build_input_content(run_context_prompt)
        stream = await agent.astream_events(
            {"messages": history_messages + [HumanMessage(content=input_content)]},
            version="v3",
            context=SessionContext(self.session_id),
        )
        async with stream:
            result_state = await self._consume_event_stream(stream, callback)
        return result_state.get("messages", []) if result_state else []

    async def _consume_event_stream(
        self,
        stream: Any,
        callback: StreamCallbackHandler | None,
    ) -> dict[str, Any] | None:
        """Consume DeepAgents v3 projections and return the final output state."""

        if callback is None:
            return await _stream_output(stream)

        message_iter = _projection_aiter(stream, "messages")
        tool_call_iter = _projection_aiter(stream, "tool_calls")
        subagent_iter = _projection_aiter(stream, "subagents")
        if message_iter is None and tool_call_iter is None and subagent_iter is None:
            return await _stream_output(stream)

        async with asyncio.TaskGroup() as task_group:
            if message_iter is not None:
                task_group.create_task(
                    _consume_message_streams(
                        message_iter,
                        callback=callback,
                        agent_name=None,
                        include_in_assistant_text=True,
                    )
                )
            if tool_call_iter is not None:
                task_group.create_task(
                    _consume_tool_call_streams(
                        tool_call_iter,
                        callback=callback,
                        agent_name=None,
                        agent_path=None,
                    )
                )
            if subagent_iter is not None:
                task_group.create_task(
                    _consume_subagent_streams(
                        subagent_iter,
                        callback=callback,
                    )
                )

        return await _stream_output(stream)

    def main_agent(self, *, streaming: bool, main_system_prompt: str) -> Any:
        """Return the cached session main agent for the requested mode."""

        if streaming:
            if self._main_agent is None:
                self._main_agent = self._create_main_agent(
                    streaming=True,
                    main_system_prompt=main_system_prompt,
                )
            return self._main_agent

        if self._fallback_agent is None:
            self._fallback_agent = self._create_main_agent(
                streaming=False,
                main_system_prompt=main_system_prompt,
            )
        return self._fallback_agent

    def _create_main_agent(self, *, streaming: bool, main_system_prompt: str) -> Any:
        """Create the DeepAgent runnable for this session."""

        skill_sources = _main_agent_skills()
        self._agent_model_names = self.current_agent_model_names()
        llm = self.build_llm("main_agent", streaming=streaming)
        return create_deep_agent(
            llm,
            tools=self.selected_builtin_tools() + self.mcp_router_tools("main_agent"),
            context_schema=SessionContext,
            backend=self.build_backend(),
            skills=skill_sources,
            system_prompt=main_system_prompt,
            middleware=[ToolCallIdMiddleware()],
            subagents=self.build_subagents(skill_sources),
        )

    def build_input_content(self, run_context_prompt: str) -> str:
        """Attach per-turn context without rebuilding the session main agent."""

        if not run_context_prompt.strip():
            return self.input_text
        return (
            "Use the following context for this request.\n\n"
            f"{run_context_prompt}\n\n"
            "User request:\n"
            f"{self.input_text}"
        )

    def build_subagents(self, skill_sources: list[str]) -> list[dict[str, Any]]:
        """Return inner DeepAgent task subagents exposed to the main agent."""

        subagents = [
            {
                **GENERAL_PURPOSE_SUBAGENT,
                "skills": skill_sources,
                "tools": [
                    *GENERAL_PURPOSE_SUBAGENT.get("tools", []),
                    *self.mcp_router_tools("general-purpose"),
                ],
                "middleware": [ToolCallIdMiddleware()],
            }
        ]
        subagents.extend(
            subagent_class.to_deepagent_config(
                build_llm=self.build_llm,
                extra_tools=self.mcp_router_tools(subagent_class.name),
            )
            for subagent_class in self.specialized_subagent_classes()
        )
        return subagents

    def specialized_subagent_classes(self) -> tuple[type[SubAgent], ...]:
        """Return automatically discovered specialized DeepAgent subagents."""

        return load_subagent_classes()

    def build_llm(
        self,
        agent_name: str | None = None,
        *,
        streaming: bool = True,
    ) -> Any:
        """Create a LangChain chat model for the requested agent."""

        config = self.agent_config(agent_name)
        provider = config.provider.lower()
        model_name = config.model.lower()
        # Claude-compatible configs may arrive with a generic provider name;
        # LangChain needs the Anthropic provider to select the right client.
        if model_name.startswith("claude") or "anthropic" in model_name:
            provider = "anthropic"

        base_url = config.base_url
        # Anthropic clients expect the base host, while many proxy configs are
        # stored with an OpenAI-compatible /v1 suffix.
        if provider == "anthropic" and base_url and base_url.endswith("/v1"):
            base_url = base_url.rsplit("/v1", 1)[0]

        model_kwargs: dict[str, Any] = {}
        if config.enable_1m_context:
            # 1M-context support is provider-specific and must be passed through
            # the provider's native opt-in parameter.
            if provider == "openai":
                model_kwargs["enable_1m_context"] = True
            elif provider == "anthropic":
                model_kwargs["betas"] = ["context-1m-2025-08-07"]

        init_kwargs: dict[str, Any] = {
            "model": config.model,
            "model_provider": provider,
            "api_key": config.api_key,
            "base_url": base_url,
            "streaming": streaming,
            "max_retries": 5,
        }
        if not streaming:
            init_kwargs["disable_streaming"] = True
        elif provider == "openai":
            init_kwargs["stream_chunk_timeout"] = None
            if base_url:
                init_kwargs["stream_usage"] = False

        if self.payload.temperature is not None:
            init_kwargs["temperature"] = self.payload.temperature
        if self.payload.max_tokens is not None:
            init_kwargs["max_tokens"] = self.payload.max_tokens

        return init_chat_model(**init_kwargs, **model_kwargs)

    def agent_config(self, agent_name: str | None) -> LLMConfig:
        """Return the per-agent model config, falling back to session default."""

        if agent_name and agent_name in self.agent_configs:
            return self.agent_configs[agent_name]
        return self.config

    def agent_model_name(self, agent_name: str) -> str:
        """Return the resolved model name used for persisted message metadata."""

        if self._agent_model_names and agent_name in self._agent_model_names:
            return self._agent_model_names[agent_name]
        return self.agent_config(agent_name).model

    def agent_model_names(self) -> dict[str, str]:
        """Return model names for the current session agent graph."""

        if self._agent_model_names is not None:
            return dict(self._agent_model_names)
        return self.current_agent_model_names()

    def current_agent_model_names(self) -> dict[str, str]:
        """Return model names for the currently configured session agents."""

        model_names = {"main_agent": self.agent_config("main_agent").model}
        model_names.update(
            {
                subagent_class.name: self.agent_config(subagent_class.name).model
                for subagent_class in self.specialized_subagent_classes()
            }
        )
        return model_names

    def selected_builtin_tools(self) -> list[Any]:
        """Return built-in tools enabled by the run payload."""

        if self.payload.tools is None:
            return []
        return [tool for tool in agent_tools if tool.name in self.payload.tools]

    def mcp_servers_for_agent(self, agent_name: str | None) -> list[str]:
        """Return configured MCP server names for the requested agent."""

        if agent_name in (None, "main_agent"):
            return _normalize_mcp_server_names(self.payload.mcp_servers)
        agent_mcp_servers = self.payload.agent_mcp_servers or {}
        return _normalize_mcp_server_names(agent_mcp_servers.get(agent_name))

    def mcp_router_tools(self, agent_name: str = "main_agent") -> list[Any]:
        """Return stable MCP router tools for a cached session agent."""

        if agent_name not in self._mcp_router_tools_by_agent:
            self._mcp_router_tools_by_agent[agent_name] = (
                create_dynamic_mcp_router_tools(
                    lambda agent_name=agent_name: self.mcp_servers_for_agent(
                        agent_name
                    ),
                )
            )
        return self._mcp_router_tools_by_agent[agent_name]

    def build_backend(self) -> CompositeBackend:
        """Create the DeepAgent backend for session-local file operations."""

        data_path = get_data_path(self.session_id)
        routes = {
            f"{str(data_path.absolute())}/": FilesystemBackend(
                data_path,
                virtual_mode=True,
                max_file_size_mb=1000,
            )
        }
        if SKILLS_ROOT.is_dir():
            skills_root = SKILLS_ROOT.resolve()
            routes[f"{skills_root.as_posix().rstrip('/')}/"] = FilesystemBackend(
                skills_root,
                virtual_mode=True,
                max_file_size_mb=10,
            )

        # Expose the host path for components outside bwrap, such as MCP servers.
        return CompositeBackend(
            default=SessionSandboxedBackend(self.session_id),
            routes=routes,
        )


def _normalize_mcp_server_names(server_names: Any) -> list[str]:
    if not server_names:
        return []

    normalized = []
    seen = set()
    for server_name in server_names:
        name = str(server_name).strip()
        if not name or name in seen:
            continue
        seen.add(name)
        normalized.append(name)
    return normalized


def _projection_aiter(target: Any, name: str) -> AsyncIterator[Any] | None:
    """Subscribe to a named async v3 stream projection if it exists."""

    projection = getattr(target, name, None)
    if projection is None:
        extensions = getattr(target, "extensions", None)
        getter = getattr(extensions, "get", None)
        if getter is not None:
            projection = getter(name)
    return _value_aiter(projection)


def _value_aiter(value: Any) -> AsyncIterator[Any] | None:
    if value is None:
        return None
    aiter_method = getattr(value, "__aiter__", None)
    if aiter_method is None:
        return None
    return aiter_method()


async def _stream_output(stream: Any) -> dict[str, Any] | None:
    output = getattr(stream, "output", None)
    if output is None:
        return None
    result = output() if callable(output) else output
    if inspect.isawaitable(result):
        result = await result
    return result if isinstance(result, dict) else None


async def _message_output(message_stream: Any) -> Any:
    output = getattr(message_stream, "output", None)
    if output is not None:
        result = output() if callable(output) else output
    else:
        result = message_stream
    if inspect.isawaitable(result):
        return await result
    return result


async def _consume_message_streams(
    message_iter: AsyncIterator[Any],
    *,
    callback: StreamCallbackHandler,
    agent_name: str | None,
    include_in_assistant_text: bool,
) -> None:
    async with asyncio.TaskGroup() as task_group:
        async for message_stream in message_iter:
            text_iter = _value_aiter(getattr(message_stream, "text", None))
            reasoning_iter = _value_aiter(
                getattr(message_stream, "reasoning", None)
            )
            task_group.create_task(
                _consume_message_stream(
                    message_stream,
                    text_iter=text_iter,
                    reasoning_iter=reasoning_iter,
                    callback=callback,
                    agent_name=agent_name,
                    include_in_assistant_text=include_in_assistant_text,
                )
            )


async def _consume_message_stream(
    message_stream: Any,
    *,
    text_iter: AsyncIterator[Any] | None,
    reasoning_iter: AsyncIterator[Any] | None,
    callback: StreamCallbackHandler,
    agent_name: str | None,
    include_in_assistant_text: bool,
) -> None:
    async with asyncio.TaskGroup() as task_group:
        if text_iter is not None:
            task_group.create_task(
                _consume_text_deltas(
                    text_iter,
                    callback=callback,
                    segment_type="text",
                    agent_name=agent_name,
                    include_in_assistant_text=include_in_assistant_text,
                )
            )
        if reasoning_iter is not None:
            task_group.create_task(
                _consume_text_deltas(
                    reasoning_iter,
                    callback=callback,
                    segment_type="thinking",
                    agent_name=agent_name,
                    include_in_assistant_text=include_in_assistant_text,
                )
            )
        output_message = await _message_output(message_stream)

    callback.record_token_usage(getattr(output_message, "usage_metadata", None))


async def _consume_text_deltas(
    delta_iter: AsyncIterator[Any],
    *,
    callback: StreamCallbackHandler,
    segment_type: str,
    agent_name: str | None,
    include_in_assistant_text: bool,
) -> None:
    async for delta in delta_iter:
        callback.record_token(
            _stringify_stream_value(delta),
            segment_type=segment_type,
            agent_name=agent_name,
            include_in_assistant_text=include_in_assistant_text,
        )


async def _consume_tool_call_streams(
    tool_call_iter: AsyncIterator[Any],
    *,
    callback: StreamCallbackHandler,
    agent_name: str | None,
    agent_path: str | None,
) -> None:
    async with asyncio.TaskGroup() as task_group:
        async for tool_call in tool_call_iter:
            tool_name = _tool_call_name(tool_call)
            event_id = _tool_call_id(tool_call, tool_name)
            callback.record_tool_start(
                tool_name=tool_name,
                event_id=event_id,
                input_text=_json_text(getattr(tool_call, "input", None)),
                agent_name=agent_name,
                agent_path=agent_path,
            )
            delta_iter = _value_aiter(getattr(tool_call, "output_deltas", None))
            task_group.create_task(
                _consume_tool_call(
                    tool_call,
                    delta_iter=delta_iter,
                    callback=callback,
                    tool_name=tool_name,
                    event_id=event_id,
                    agent_name=agent_name,
                    agent_path=agent_path,
                )
            )


async def _consume_tool_call(
    tool_call: Any,
    *,
    delta_iter: AsyncIterator[Any] | None,
    callback: StreamCallbackHandler,
    tool_name: str,
    event_id: str,
    agent_name: str | None,
    agent_path: str | None,
) -> None:
    output_parts: list[str] = []
    try:
        if delta_iter is not None:
            async for delta in delta_iter:
                output_parts.append(_stringify_stream_value(delta))
    except BaseException as exc:
        callback.record_tool_error(
            tool_name=tool_name,
            event_id=event_id,
            output_text=str(exc),
            agent_name=agent_name,
            agent_path=agent_path,
        )
        raise

    error = getattr(tool_call, "error", None)
    if error:
        callback.record_tool_error(
            tool_name=tool_name,
            event_id=event_id,
            output_text=str(error),
            agent_name=agent_name,
            agent_path=agent_path,
        )
        return

    output = getattr(tool_call, "output", None)
    output_text = (
        "".join(output_parts)
        if output is None and output_parts
        else _stringify_stream_value(output)
    )
    callback.record_tool_end(
        tool_name=tool_name,
        event_id=event_id,
        output_text=output_text,
        agent_name=agent_name,
        agent_path=agent_path,
    )


async def _consume_subagent_streams(
    subagent_iter: AsyncIterator[Any],
    *,
    callback: StreamCallbackHandler,
) -> None:
    async with asyncio.TaskGroup() as task_group:
        async for subagent in subagent_iter:
            name = _subagent_name(subagent)
            path = _subagent_path(subagent)
            callback.record_subagent_start(
                name=name,
                path=path,
                task_input=getattr(subagent, "task_input", None),
            )
            message_iter = _projection_aiter(subagent, "messages")
            tool_call_iter = _projection_aiter(subagent, "tool_calls")
            nested_subagent_iter = _projection_aiter(subagent, "subagents")
            task_group.create_task(
                _consume_subagent(
                    subagent,
                    message_iter=message_iter,
                    tool_call_iter=tool_call_iter,
                    nested_subagent_iter=nested_subagent_iter,
                    callback=callback,
                    name=name,
                    path=path,
                )
            )


async def _consume_subagent(
    subagent: Any,
    *,
    message_iter: AsyncIterator[Any] | None,
    tool_call_iter: AsyncIterator[Any] | None,
    nested_subagent_iter: AsyncIterator[Any] | None,
    callback: StreamCallbackHandler,
    name: str | None,
    path: str,
) -> None:
    status: str | None = None
    error: str | None = None
    try:
        async with asyncio.TaskGroup() as task_group:
            if message_iter is not None:
                task_group.create_task(
                    _consume_message_streams(
                        message_iter,
                        callback=callback,
                        agent_name=name,
                        include_in_assistant_text=False,
                    )
                )
            if tool_call_iter is not None:
                task_group.create_task(
                    _consume_tool_call_streams(
                        tool_call_iter,
                        callback=callback,
                        agent_name=name,
                        agent_path=path,
                    )
                )
            if nested_subagent_iter is not None:
                task_group.create_task(
                    _consume_subagent_streams(
                        nested_subagent_iter,
                        callback=callback,
                    )
                )

        await _stream_output(subagent)
        status = getattr(subagent, "status", None) or "completed"
        error = getattr(subagent, "error", None)
    except BaseException as exc:
        status = getattr(subagent, "status", None) or (
            "cancelled" if isinstance(exc, asyncio.CancelledError) else "failed"
        )
        error = getattr(subagent, "error", None)
        if error is None and not isinstance(exc, asyncio.CancelledError):
            error = str(exc)
        raise
    finally:
        callback.record_subagent_end(
            name=name,
            path=path,
            status=status,
            error=error,
        )


def _tool_call_name(tool_call: Any) -> str:
    return str(
        getattr(tool_call, "tool_name", None)
        or getattr(tool_call, "name", None)
        or "tool"
    )


def _tool_call_id(tool_call: Any, tool_name: str) -> str:
    return str(
        getattr(tool_call, "tool_call_id", None)
        or getattr(tool_call, "id", None)
        or f"{tool_name}-{id(tool_call)}"
    )


def _subagent_name(subagent: Any) -> str | None:
    name = getattr(subagent, "name", None) or getattr(subagent, "graph_name", None)
    return str(name) if name is not None else None


def _subagent_path(subagent: Any) -> str:
    path = getattr(subagent, "path", None) or ()
    if isinstance(path, str):
        return path
    return "/".join(str(segment) for segment in path)


def _json_text(value: Any) -> str:
    if value is None:
        return ""
    try:
        return json.dumps(value, ensure_ascii=False, default=str)
    except TypeError:
        return str(value)


def _stringify_stream_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    content = getattr(value, "content", None)
    if content is not None and not isinstance(value, (dict, list)):
        return _stringify_stream_value(content)
    return _json_text(value)


def _delegation_rule(subagent_class: type[SubAgent]) -> str:
    return subagent_class.delegation_rule or _default_delegation_rule(subagent_class)


def _default_delegation_rule(subagent_class: type[SubAgent]) -> str:
    return (
        f"Call `task` with `{subagent_class.name}` when its description fits "
        "the current user request or workflow step."
    )


def _main_agent_skills() -> list[str]:
    """Return local DeepAgent skill source folders for the main agent."""

    if not SKILLS_ROOT.is_dir():
        return []

    sources = [
        (SKILLS_ROOT / source_name).resolve().as_posix()
        for source_name in MAIN_AGENT_SKILL_SOURCE_DIRS
        if _has_skill_dirs(SKILLS_ROOT / source_name)
    ]
    if _has_skill_dirs(SKILLS_ROOT):
        sources.append(SKILLS_ROOT.resolve().as_posix())
    return sources


def _has_skill_dirs(source: Path) -> bool:
    if not source.is_dir():
        return False
    return any(
        child.is_dir() and (child / "SKILL.md").is_file()
        for child in source.iterdir()
    )
