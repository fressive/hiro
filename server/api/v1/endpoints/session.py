"""Agent API endpoints."""

import asyncio
import json
import time
import os
import shutil
from pathlib import Path
from contextlib import AsyncExitStack
from datetime import datetime, timezone
from typing import AsyncGenerator, Any, List

from deepagents import create_deep_agent
from deepagents.backends import LocalShellBackend, FilesystemBackend, CompositeBackend, StateBackend
from deepagents.middleware.subagents import GENERAL_PURPOSE_SUBAGENT
from fastapi import APIRouter, Depends, HTTPException, File, UploadFile
from fastapi.responses import StreamingResponse, FileResponse
from langchain.chat_models import init_chat_model
from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.messages import HumanMessage, AIMessage, ToolMessage, BaseMessage
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from server.agent.context import SessionContext
from server.agent.tools import agent_tools
from server.agent.sandboxed_backend import SessionSandboxedBackend
from server.agent.tool_call_ids import (
    ToolCallIdMiddleware,
    is_valid_tool_call_id,
    normalize_ai_message_tool_call_ids,
    normalize_model_messages,
)
from server.db import get_session, AsyncSessionLocal
from server.models.models import LLMConfig, AgentSession, AgentMessage, MCPServerConfig
from server.service.rag_service import RagService
from server.service.mcp_service import McpService
from server.core.logger import logger
from server.core.util import get_data_path
from server.models.schemas import (
    AgentRunRequest,
    AgentSessionCreate,
    AgentSessionUpdate,
    AgentSessionResponse,
    AgentMessageResponse,
    ToolResponse,
    SessionFileResponse,
)

router = APIRouter()

# Global registry for active agent tasks: session_id -> asyncio.Task
_active_agent_tasks: dict[int, asyncio.Task] = {}


@router.post("/sessions/{session_id}/stop")
async def stop_agent(session_id: int):
    """Stop a running agent task for the given session."""
    task = _active_agent_tasks.get(session_id)
    if not task or task.done():
        return {"message": "No active agent task found for this session"}
    
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    
    if session_id in _active_agent_tasks:
        del _active_agent_tasks[session_id]
        
    return {"message": "Agent task stopped successfully"}


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
        # Convert list of blocks to a JSON string to preserve all block types (thinking, text, etc.)
        import json
        return json.dumps(content)
    content_blocks = getattr(message, "content_blocks", None)
    if isinstance(content_blocks, list):
        import json
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
                    *_metadata_usage_candidates(getattr(generation, "generation_info", None)),
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
        self._usage: dict[str, int] = {"input_tokens": 0, "output_tokens": 0, "cached_input_tokens": 0}

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
        """Capture token usage if available."""
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


@router.get("/tools", response_model=List[ToolResponse])
async def list_tools():
    """List all available tools."""
    return [
        ToolResponse(name=tool.name, description=tool.description)
        for tool in agent_tools
    ]


@router.get("/sessions/{session_id}/status")
async def get_session_status(session_id: int):
    """Check if an agent is currently running for this session."""
    task = _active_agent_tasks.get(session_id)
    return {"is_running": task is not None and not task.done()}


@router.post("/run")
async def run_agent(
    payload: AgentRunRequest, session: AsyncSession = Depends(get_session)
):
    """Stream agent output using a configured LLM."""
    if not payload.input.strip():
        raise HTTPException(status_code=400, detail="Input is required")

    active_session: AgentSession | None = None
    if payload.session_id is not None:
        result = await session.execute(
            select(AgentSession).where(AgentSession.id == payload.session_id)
        )
        active_session = result.scalars().first()
        if not active_session:
            raise HTTPException(status_code=404, detail="Session not found")
    else:
        active_session = AgentSession(
            title=payload.input.strip()[:80],
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        session.add(active_session)
        await session.commit()
        await session.refresh(active_session)

    # Check if already running
    if active_session.id in _active_agent_tasks:
        task = _active_agent_tasks[active_session.id]
        if not task.done():
            raise HTTPException(status_code=409, detail="An agent is already running for this session")

    # Save/Update session configuration from the request
    active_session.config_id = payload.config_id
    active_session.system_prompt = payload.system_prompt
    active_session.temperature = payload.temperature
    active_session.max_tokens = payload.max_tokens
    active_session.enable_1m_context = payload.enable_1m_context
    active_session.is_deep_agent = payload.is_deep_agent
    active_session.enable_rag = payload.enable_rag
    active_session.tools = payload.tools
    active_session.mcp_servers = payload.mcp_servers
    
    # Explicitly flag JSON fields as modified to ensure SQLAlchemy persists them
    flag_modified(active_session, "tools")
    flag_modified(active_session, "mcp_servers")
    
    await session.commit()
    await session.refresh(active_session)
    logger.info(f"Session {active_session.id} config updated. Tools: {active_session.tools}, MCP: {active_session.mcp_servers}")
    
    active_session_id = active_session.id

    result = await session.execute(
        select(LLMConfig).where(LLMConfig.id == payload.config_id)
    )
    config = result.scalars().first()
    if not config:
        raise HTTPException(status_code=404, detail="LLM config not found")

    provider = config.provider.lower()
    
    # Force 'anthropic' provider for Claude models to ensure correct header/routing
    if config.model.lower().startswith("claude") or "anthropic" in config.model.lower():
        provider = "anthropic"
    
    base_url = config.base_url
    if provider == "anthropic" and base_url and base_url.endswith("/v1"):
        base_url = base_url.rsplit("/v1", 1)[0]
    
    # Prepare model kwargs for beta features
    model_kwargs = {}
    if config.enable_1m_context:
        if provider == "openai":
            model_kwargs["enable_1m_context"] = True
        elif provider == "anthropic":
            # init_chat_model for anthropic provider supports 'betas' if passed correctly
            model_kwargs["betas"] = ["context-1m-2025-08-07"]

    # Use init_chat_model to match test script behavior
    init_kwargs = {
        "model": config.model,
        "model_provider": provider,
        "api_key": config.api_key,
        "base_url": base_url,
        "streaming": True,
        "max_retries": 5,
    }
    
    if payload.temperature is not None:
        init_kwargs["temperature"] = payload.temperature
    if payload.max_tokens is not None:
        init_kwargs["max_tokens"] = payload.max_tokens

    llm = init_chat_model(
        **init_kwargs,
        **model_kwargs
    )

    # Filter tools if requested
    selected_tools = []
    if payload.tools is not None:
        selected_tools = [t for t in agent_tools if t.name in payload.tools]

    # Handle RAG retrieval
    rag_context = ""
    rag_sources = []
    if payload.enable_rag:
        try:
            hits = await RagService.search(payload.input.strip(), limit=5)
            if hits:
                context_parts = []
                for hit in hits:
                    source = hit.get("title", "Unknown")
                    text = hit.get("text", "")
                    context_parts.append(f"--- Source: {source} ---\n{text}")
                    if source not in rag_sources:
                        rag_sources.append(source)
                rag_context = "\n\n".join(context_parts)
        except Exception as exc:
            # Don't fail the whole run if RAG fails, but log it
            print(f"RAG retrieval failed: {exc}")

    async def stream() -> AsyncGenerator[str, None]:
        queue: asyncio.Queue[str | None] = asyncio.Queue()
        loop = asyncio.get_running_loop()
        callback = _StreamCallbackHandler(queue, loop)
        await queue.put(
            _format_sse(
            "session",
                {"id": active_session_id, "title": active_session.title},
            )
        )
        
        if rag_sources:
            await queue.put(
                _format_sse(
                    "rag_search",
                    {"sources": rag_sources},
                )
            )

        async def _run_agent() -> None:
            async with AsyncExitStack() as exit_stack:
                try:
                    # Save user message immediately using a fresh session
                    async with AsyncSessionLocal() as db_session:
                        user_message = AgentMessage(
                            session_id=active_session_id,
                            role="user",
                            content=payload.input.strip(),
                            created_at=datetime.now(timezone.utc),
                        )
                        db_session.add(user_message)
                        
                        # Update session activity
                        sess_result = await db_session.execute(
                            select(AgentSession).where(AgentSession.id == active_session_id)
                        )
                        db_sess = sess_result.scalars().first()
                        if db_sess:
                            db_sess.updated_at = datetime.now(timezone.utc)
                            if not db_sess.title:
                                db_sess.title = payload.input.strip()[:80]
                        
                        await db_session.commit()

                    # Create assistant message placeholder
                    assistant_msg_id = None
                    async with AsyncSessionLocal() as db_session:
                        assistant_message = AgentMessage(
                            session_id=active_session_id,
                            role="assistant",
                            content="",
                            model=config.model,
                            created_at=datetime.now(timezone.utc),
                        )
                        db_session.add(assistant_message)
                        await db_session.commit()
                        await db_session.refresh(assistant_message)
                        assistant_msg_id = assistant_message.id

                    # Periodically update assistant message in DB
                    agent_done = asyncio.Event()
                    async def update_periodically():
                        last_saved = ""
                        while not agent_done.is_set():
                            try:
                                await asyncio.sleep(2)
                                current = callback.token_text
                                if current != last_saved:
                                    async with AsyncSessionLocal() as db_session:
                                        msg = await db_session.get(AgentMessage, assistant_msg_id)
                                        if msg:
                                            msg.content = current
                                            await db_session.commit()
                                            last_saved = current
                            except Exception as e:
                                logger.error(f"Error in periodic update: {e}")

                    update_task = asyncio.create_task(update_periodically())

                    # Load MCP tools
                    mcp_tools = []
                    if payload.mcp_servers:
                        logger.info(f"Loading tools from MCP servers: {payload.mcp_servers}")
                        async with AsyncSessionLocal() as db_session:
                            mcp_configs_result = await db_session.execute(
                                select(MCPServerConfig).where(MCPServerConfig.name.in_(payload.mcp_servers))
                            )
                            found_configs = mcp_configs_result.scalars().all()
                            if found_configs:
                                mcp_tools = await McpService.load_mcp_tools(found_configs, exit_stack)
                    
                    current_tools = selected_tools + mcp_tools
                    data_path = get_data_path(active_session_id)
                    context = SessionContext(active_session_id)
                    backend = CompositeBackend(
                        default=StateBackend(),
                        routes={
                            f"{str(data_path.absolute())}/": FilesystemBackend(data_path, virtual_mode=True, max_file_size_mb=1000)
                        }
                    )
                    
                    # Fetch history using fresh session
                    history_messages: list[BaseMessage] = []
                    pending_tool_calls: list[dict[str, str | None]] = []
                    async with AsyncSessionLocal() as db_session:
                        result = await db_session.execute(
                            select(AgentMessage)
                            .where(AgentMessage.session_id == active_session_id)
                            .order_by(AgentMessage.created_at.asc())
                        )
                        db_messages = result.scalars().all()
                        for message in db_messages:
                            # Skip the ones we just added (the user message and the empty assistant message)
                            created_at = message.created_at
                            if created_at.tzinfo is None:
                                created_at = created_at.replace(tzinfo=timezone.utc)
                            
                            if message.id == assistant_msg_id or (message.role == "user" and message.content == payload.input.strip() and (datetime.now(timezone.utc) - created_at).total_seconds() < 5):
                                continue

                            if message.role == "assistant":
                                if not message.content and not message.tool_calls:
                                    continue
                                ai_message = normalize_ai_message_tool_call_ids(
                                    AIMessage(content=message.content, tool_calls=message.tool_calls or [])
                                )
                                history_messages.append(ai_message)
                                for tool_call in getattr(ai_message, "tool_calls", []):
                                    tool_call_id = tool_call.get("id")
                                    if is_valid_tool_call_id(tool_call_id):
                                        pending_tool_calls.append(
                                            {"id": tool_call_id, "name": tool_call.get("name")}
                                        )
                            elif message.role == "tool":
                                tcid = message.tool_call_id
                                if not is_valid_tool_call_id(tcid):
                                    matching_indexes = [
                                        index for index, tool_call in enumerate(pending_tool_calls)
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
                                        continue
                                else:
                                    matching_index = next(
                                        (
                                            index for index, tool_call in enumerate(pending_tool_calls)
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
                                        continue
                                    pending_tool_calls.pop(matching_index)
                                history_messages.append(
                                    ToolMessage(
                                        content=message.content,
                                        tool_call_id=tcid,
                                        name=message.name,
                                    )
                                )
                            else:
                                history_messages.append(HumanMessage(content=message.content))

                    for tool_call in pending_tool_calls:
                        history_messages.append(
                            ToolMessage(
                                content=f"Tool call {tool_call['name'] or 'unknown'} was cancelled before a result was saved.",
                                tool_call_id=tool_call["id"],
                                name=tool_call["name"],
                                status="error",
                            )
                        )

                    # Construct full system prompt
                    full_system_prompt = payload.system_prompt or ""
                    if mcp_tools:
                        mcp_tools_info = "\n".join([f"- {t.name}: {t.description}" for t in mcp_tools])
                        full_system_prompt += f"\n\nYou have access to the following MCP tools:\n{mcp_tools_info}"
                    if rag_context:
                        full_system_prompt += f"\n\nRELEVANT CONTEXT FROM DOCUMENTS:\n{rag_context}"

                    # Execution
                    if payload.is_deep_agent:
                        skills_sources = ["./skills"]
                        agent = create_deep_agent(
                            llm,
                            tools=current_tools,
                            context_schema=SessionContext,
                            backend=backend,
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
                            {"messages": history_messages + [HumanMessage(content=payload.input.strip())]},
                            config={"callbacks": [callback]},
                            context=context,
                        )
                        all_messages = result_state.get("messages", [])
                    else:
                        from langchain_core.messages import SystemMessage
                        llm_messages = []
                        if full_system_prompt:
                            llm_messages.append(SystemMessage(content=full_system_prompt))
                        llm_messages.extend(history_messages)
                        llm_messages.append(HumanMessage(content=payload.input.strip()))
                        llm_with_tools = llm.bind_tools(current_tools) if current_tools else llm
                        result_payload = await llm_with_tools.ainvoke(
                            llm_messages,
                            config={"callbacks": [callback]},
                        )
                        result_messages = result_payload if isinstance(result_payload, list) else [result_payload]
                        all_messages = (
                            history_messages
                            + [HumanMessage(content=payload.input.strip())]
                            + normalize_model_messages(result_messages)
                        )

                    # Final Save
                    agent_done.set()
                    await update_task
                    
                    # history_messages has N messages, payload.input adds 1, so AI responses start at index N+1
                    new_messages = [
                        normalize_ai_message_tool_call_ids(msg) if isinstance(msg, BaseMessage) else msg
                        for msg in all_messages[len(history_messages) + 1:]
                    ]
                    assistant_text = ""
                    
                    async with AsyncSessionLocal() as db_session:
                        for i, msg in enumerate(new_messages):
                            role = "user"
                            content = _extract_message_text(msg)
                            if isinstance(msg, AIMessage):
                                role = "assistant"
                                if not assistant_text and not msg.tool_calls:
                                    assistant_text = content
                                
                                # Update the placeholder assistant message if it's the first one
                                if i == 0 or (i == 1 and new_messages[0].role == "user"):
                                    msg_to_update = await db_session.get(AgentMessage, assistant_msg_id)
                                    if msg_to_update:
                                        msg_to_update.content = content
                                        msg_to_update.tool_calls = msg.tool_calls
                                        # Capture usage
                                        usage = getattr(msg, "usage_metadata", {})
                                        msg_to_update.input_tokens = usage.get("input_tokens") or callback.usage["input_tokens"]
                                        msg_to_update.output_tokens = usage.get("output_tokens") or callback.usage["output_tokens"]
                                        msg_to_update.cached_input_tokens = usage.get("cache_read_input_tokens") or callback.usage["cached_input_tokens"]
                                        continue

                            elif isinstance(msg, ToolMessage): role = "tool"
                            elif isinstance(msg, HumanMessage): role = "user"

                            db_msg = AgentMessage(session_id=active_session_id, role=role, content=content, name=getattr(msg, "name", None), tool_call_id=getattr(msg, "tool_call_id", None), tool_calls=getattr(msg, "tool_calls", None), created_at=datetime.now(timezone.utc))
                            
                            if isinstance(msg, AIMessage):
                                usage = getattr(msg, "usage_metadata", {})
                                if usage:
                                    db_msg.input_tokens = usage.get("input_tokens")
                                    db_msg.output_tokens = usage.get("output_tokens")
                                    cached_tokens = usage.get("cache_read_input_tokens") or 0
                                    if not cached_tokens and "input_token_details" in usage:
                                        cached_tokens = usage["input_token_details"].get("cache_read") or 0
                                    db_msg.cached_input_tokens = cached_tokens
                            
                            db_session.add(db_msg)
                        await db_session.commit()

                    if not assistant_text: assistant_text = callback.token_text
                    await queue.put(_format_sse("done", {"text": assistant_text, "session_id": active_session_id}))

                except Exception as exc:
                    logger.error(f"Agent execution error: {exc}")
                    async with AsyncSessionLocal() as db_session:
                        error_message = AgentMessage(session_id=active_session_id, role="assistant", content=f"Error: {exc}", created_at=datetime.now(timezone.utc))
                        db_session.add(error_message)
                        await db_session.commit()
                    await queue.put(_format_sse("error", {"message": str(exc), "session_id": active_session_id}))
                finally:
                    agent_done.set()
                    if active_session_id in _active_agent_tasks:
                        del _active_agent_tasks[active_session_id]
                    await queue.put(None)

        agent_task = asyncio.create_task(_run_agent())
        _active_agent_tasks[active_session_id] = agent_task

        try:
            while True:
                message = await queue.get()
                if message is None:
                    break
                yield message
        finally:
            # On client disconnect, we DO NOT cancel the agent task anymore.
            # This allows it to finish and the user to see the result upon refresh.
            logger.info(f"Client disconnected for session {active_session_id}. Agent task continues in background.")

    return StreamingResponse(stream(), media_type="text/event-stream")


@router.get("/sessions", response_model=list[AgentSessionResponse])
async def list_sessions(session: AsyncSession = Depends(get_session)):
    result = await session.execute(
        select(AgentSession).order_by(desc(AgentSession.updated_at))
    )
    return result.scalars().all()


@router.post("/sessions", response_model=AgentSessionResponse)
async def create_session(
    payload: AgentSessionCreate, session: AsyncSession = Depends(get_session)
):
    created = AgentSession(
        title=payload.title,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    session.add(created)
    await session.commit()
    await session.refresh(created)
    return created


@router.patch("/sessions/{session_id}", response_model=AgentSessionResponse)
async def update_session(
    session_id: int, 
    payload: AgentSessionUpdate, 
    session: AsyncSession = Depends(get_session)
):
    result = await session.execute(
        select(AgentSession).where(AgentSession.id == session_id)
    )
    db_session = result.scalars().first()
    if not db_session:
        raise HTTPException(status_code=404, detail="Session not found")

    update_data = payload.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(db_session, key, value)
        if key in ["tools", "mcp_servers"]:
            flag_modified(db_session, key)

    db_session.updated_at = datetime.now(timezone.utc)
    await session.commit()
    await session.refresh(db_session)
    logger.info(f"Session {db_session.id} patched. Tools: {db_session.tools}, MCP: {db_session.mcp_servers}")
    return db_session

@router.get("/sessions/{session_id}/messages", response_model=list[AgentMessageResponse])
async def list_messages(session_id: int, session: AsyncSession = Depends(get_session)):
    result = await session.execute(
        select(AgentSession).where(AgentSession.id == session_id)
    )
    active = result.scalars().first()
    if not active:
        raise HTTPException(status_code=404, detail="Session not found")

    result = await session.execute(
        select(AgentMessage)
        .where(AgentMessage.session_id == session_id)
        .order_by(AgentMessage.created_at.asc())
    )
    return result.scalars().all()


@router.delete("/sessions/{session_id}")
async def delete_session(session_id: int, session: AsyncSession = Depends(get_session)):
    result = await session.execute(
        select(AgentSession).where(AgentSession.id == session_id)
    )
    active = result.scalars().first()
    if not active:
        raise HTTPException(status_code=404, detail="Session not found")

    # Delete the data folder if it exists
    data_path = get_data_path(session_id)
    if data_path.exists():
        shutil.rmtree(data_path)

    await session.delete(active)
    await session.commit()
    return {"message": "Session deleted successfully"}


@router.get("/sessions/{session_id}/stats")
async def get_session_stats(session_id: int, session: AsyncSession = Depends(get_session)):
    """Get token usage statistics for a session."""
    result = await session.execute(
        select(AgentMessage)
        .where(AgentMessage.session_id == session_id)
        .order_by(AgentMessage.created_at.asc())
    )
    db_messages = result.scalars().all()
    
    total_input_tokens = 0
    total_cached_input_tokens = 0
    total_output_tokens = 0
    rounds = []
    model_usage = {}

    round_index = 1
    for msg in db_messages:
        if msg.role == "assistant" and (msg.input_tokens or msg.output_tokens):
            it = msg.input_tokens or 0
            ct = msg.cached_input_tokens or 0
            ot = msg.output_tokens or 0
            total_input_tokens += it
            total_cached_input_tokens += ct
            total_output_tokens += ot

            model_name = msg.model or "unknown"
            if model_name not in model_usage:
                model_usage[model_name] = {"input": 0, "cached": 0, "output": 0, "total": 0}
            model_usage[model_name]["input"] += it
            model_usage[model_name]["cached"] += ct
            model_usage[model_name]["output"] += ot
            model_usage[model_name]["total"] += (it + ot)

            rounds.append({
                "step": f"Round {round_index}",
                "tokens": it + ot,
                "input_tokens": it,
                "cached_input_tokens": ct,
                "output_tokens": ot,
                "model": model_name,
                "created_at": msg.created_at.isoformat()
            })
            round_index += 1

    return {
        "total_tokens": total_input_tokens + total_output_tokens,
        "total_input_tokens": total_input_tokens,
        "total_cached_input_tokens": total_cached_input_tokens,
        "total_output_tokens": total_output_tokens,
        "model_usage": model_usage,
        "rounds": rounds
    }

@router.get("/stats")
async def get_global_stats(session: AsyncSession = Depends(get_session)):
    """Get aggregated token usage statistics for all sessions."""
    result = await session.execute(
        select(AgentMessage)
        .where(AgentMessage.role == "assistant")
        .where((AgentMessage.input_tokens > 0) | (AgentMessage.output_tokens > 0))
        .order_by(AgentMessage.created_at.asc())
    )
    db_messages = result.scalars().all()
    
    total_input_tokens = 0
    total_cached_input_tokens = 0
    total_output_tokens = 0
    daily_usage = {}
    model_usage = {}

    for msg in db_messages:
        it = msg.input_tokens or 0
        ct = msg.cached_input_tokens or 0
        ot = msg.output_tokens or 0
        total_input_tokens += it
        total_cached_input_tokens += ct
        total_output_tokens += ot

        # Aggregate by model
        model_name = msg.model or "unknown"
        if model_name not in model_usage:
            model_usage[model_name] = {"input": 0, "cached": 0, "output": 0, "total": 0}
        model_usage[model_name]["input"] += it
        model_usage[model_name]["cached"] += ct
        model_usage[model_name]["output"] += ot
        model_usage[model_name]["total"] += (it + ot)

        # Aggregate by date
        day = msg.created_at.date().isoformat()
        if day not in daily_usage:
            daily_usage[day] = {"total": 0, "input": 0, "cached": 0, "output": 0}
        daily_usage[day]["total"] += (it + ot)
        daily_usage[day]["input"] += it
        daily_usage[day]["cached"] += ct
        daily_usage[day]["output"] += ot

    usage_over_time = [
        {
            "date": day, 
            "tokens": data["total"],
            "input_tokens": data["input"],
            "cached_input_tokens": data["cached"],
            "output_tokens": data["output"]
        }
        for day, data in sorted(daily_usage.items())
    ]

    return {
        "total_tokens": total_input_tokens + total_output_tokens,
        "total_input_tokens": total_input_tokens,
        "total_cached_input_tokens": total_cached_input_tokens,
        "total_output_tokens": total_output_tokens,
        "model_usage": model_usage,
        "usage_over_time": usage_over_time
    }

@router.get("/sessions/{session_id}/files", response_model=List[SessionFileResponse])
async def list_session_files(session_id: int, session: AsyncSession = Depends(get_session)):
    """List files in the session's data folder."""
    result = await session.execute(
        select(AgentSession).where(AgentSession.id == session_id)
    )
    if not result.scalars().first():
        raise HTTPException(status_code=404, detail="Session not found")

    data_path = get_data_path(session_id) / "data"
    files = []
    for root, dirs, filenames in os.walk(data_path):
        # Add directories
        for dirname in dirs:
            dir_path = Path(root) / dirname
            rel_path = os.path.relpath(dir_path, data_path)
            mtime = os.path.getmtime(dir_path)
            files.append({
                "path": rel_path,
                "size": 0,
                "modified_at": datetime.fromtimestamp(mtime, tz=timezone.utc).isoformat(),
                "type": "directory"
            })
        # Add files
        for filename in filenames:
            file_path = Path(root) / filename
            rel_path = os.path.relpath(file_path, data_path)
            size = os.path.getsize(file_path)
            mtime = os.path.getmtime(file_path)
            files.append({
                "path": rel_path,
                "size": size,
                "modified_at": datetime.fromtimestamp(mtime, tz=timezone.utc).isoformat(),
                "type": "file"
            })
    return files

@router.post("/sessions/{session_id}/files/upload")
async def upload_session_file(
    session_id: int, 
    file: UploadFile = File(...), 
    session: AsyncSession = Depends(get_session)
):
    """Upload a file to the session's data folder."""
    result = await session.execute(
        select(AgentSession).where(AgentSession.id == session_id)
    )
    if not result.scalars().first():
        raise HTTPException(status_code=404, detail="Session not found")

    data_path = get_data_path(session_id) / "data"
    # Basic security check: ensure the filename doesn't try to go outside the folder
    filename = os.path.basename(file.filename)
    target_path = data_path / filename
    
    with open(target_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
        
    return {"filename": filename, "status": "uploaded"}

@router.get("/sessions/{session_id}/files/download")
async def download_session_file(
    session_id: int, 
    path: str, 
    session: AsyncSession = Depends(get_session)
):
    """Download a file from the session's data folder."""
    result = await session.execute(
        select(AgentSession).where(AgentSession.id == session_id)
    )
    if not result.scalars().first():
        raise HTTPException(status_code=404, detail="Session not found")

    data_path = get_data_path(session_id) / "data"
    file_path = (data_path / path).resolve()
    
    if not str(file_path).startswith(str(data_path.resolve())):
        raise HTTPException(status_code=403, detail="Forbidden")
    
    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(status_code=404, detail="File not found")
        
    return FileResponse(path=file_path, filename=os.path.basename(file_path))

@router.delete("/sessions/{session_id}/files")
async def delete_session_file(
    session_id: int, 
    path: str, 
    session: AsyncSession = Depends(get_session)
):
    """Delete a file from the session's data folder."""
    result = await session.execute(
        select(AgentSession).where(AgentSession.id == session_id)
    )
    if not result.scalars().first():
        raise HTTPException(status_code=404, detail="Session not found")

    data_path = get_data_path(session_id) / "data"
    file_path = (data_path / path).resolve()
    
    if not str(file_path).startswith(str(data_path.resolve())):
        raise HTTPException(status_code=403, detail="Forbidden")
        
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="File not found")
        
    if file_path.is_dir():
        shutil.rmtree(file_path)
    else:
        os.remove(file_path)
        
    return {"status": "deleted"}
