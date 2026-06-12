"""Agent API endpoints."""

import asyncio
import os
import shutil
from pathlib import Path
from datetime import datetime, timezone
from typing import Any, List

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    File,
    UploadFile,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.responses import FileResponse
from pydantic import ValidationError
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from server.agent.custom_agent import CustomAgent
from server.agent.events.session_events import SessionEventHub
from server.agent.events.streaming import AgentStreamEvent
from server.agent.persistence import token_usage
from server.agent.trace.execution_trace import (
    attach_trace_metadata_fallback,
    normalize_trace_metadata,
)
from server.agent.subagents import load_subagent_classes
from server.agent.tools import agent_tools
from server.db import AsyncSessionLocal, get_session
from server.models.agent import AgentMessage, AgentSession, AgentSessionTemplate
from server.models.llm import LLMConfig
from server.core.logger import logger
from server.core.util import get_data_path
from server.schemas.agent import (
    AgentRunRequest,
    AgentSessionCreate,
    AgentSessionUpdate,
    AgentSessionResponse,
    AgentSessionTemplateCreate,
    AgentSessionTemplateUpdate,
    AgentSessionTemplateResponse,
    AgentMessageResponse,
    ToolResponse,
    SubAgentResponse,
    SessionFileResponse,
)

router = APIRouter()

# Global registry for active agent tasks: session_id -> asyncio.Task
_active_agent_tasks: dict[int, asyncio.Task] = {}
_session_event_hubs: dict[int, SessionEventHub] = {}
_session_agents: dict[int, CustomAgent] = {}


def _token_usage_parts(
    input_tokens: int | None,
    cached_input_tokens: int | None,
    output_tokens: int | None,
) -> dict[str, int]:
    normalized_input = token_usage.token_count(input_tokens)
    normalized_cached = token_usage.token_count(cached_input_tokens)
    normalized_output = token_usage.token_count(output_tokens)
    if not normalized_input and normalized_cached:
        normalized_input = normalized_cached
    elif normalized_cached > normalized_input:
        normalized_input += normalized_cached
    uncached_input = token_usage.uncached_input_tokens(
        normalized_input, normalized_cached
    )
    return {
        "input": normalized_input,
        "uncached_input": uncached_input,
        "cached": normalized_cached,
        "output": normalized_output,
        "total": normalized_input + normalized_output,
    }


def _is_session_running(session_id: int) -> bool:
    task = _active_agent_tasks.get(session_id)
    if task is None:
        return False
    if task.done():
        _active_agent_tasks.pop(session_id, None)
        return False
    return True


def _get_session_hub(session_id: int) -> SessionEventHub:
    hub = _session_event_hubs.get(session_id)
    if hub is None:
        hub = SessionEventHub()
        _session_event_hubs[session_id] = hub
    return hub


def _cleanup_session_hub(session_id: int) -> None:
    hub = _session_event_hubs.get(session_id)
    if hub is not None and not hub.has_subscribers and not _is_session_running(session_id):
        _session_event_hubs.pop(session_id, None)


def _get_session_agent(
    *,
    active_session: AgentSession,
    payload: AgentRunRequest,
    config: LLMConfig,
    agent_configs: dict[str, LLMConfig],
) -> CustomAgent:
    agent = _session_agents.get(active_session.id)
    if agent is None:
        agent = CustomAgent(
            session_id=active_session.id,
            session_title=active_session.title,
            payload=payload,
            config=config,
            agent_configs=agent_configs,
        )
        _session_agents[active_session.id] = agent
        return agent

    agent.configure_run(
        session_title=active_session.title,
        payload=payload,
        config=config,
        agent_configs=agent_configs,
    )
    return agent


def _drop_session_agent(session_id: int) -> None:
    _session_agents.pop(session_id, None)


async def _bridge_agent_events(
    session_id: int,
    source_queue: asyncio.Queue[AgentStreamEvent | None],
    hub: SessionEventHub,
) -> None:
    try:
        while True:
            event = await source_queue.get()
            if event is None:
                break
            await hub.publish(event)
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        logger.error("Agent event bridge failed for session %s: %s", session_id, exc)
    finally:
        task = _active_agent_tasks.get(session_id)
        if task is not None and task.done():
            _active_agent_tasks.pop(session_id, None)
        await hub.publish_status(is_running=False)
        _cleanup_session_hub(session_id)


async def _session_exists(session_id: int) -> bool:
    async with AsyncSessionLocal() as db_session:
        result = await db_session.execute(
            select(AgentSession.id).where(AgentSession.id == session_id)
        )
        return result.scalar_one_or_none() is not None


async def _send_websocket_events(
    websocket: WebSocket,
    hub: SessionEventHub,
    queue: asyncio.Queue[AgentStreamEvent | None],
) -> None:
    try:
        while True:
            event = await queue.get()
            if event is None:
                break
            await websocket.send_json(event.as_json())
    finally:
        hub.unsubscribe(queue)


async def _publish_websocket_error(
    hub: SessionEventHub,
    *,
    session_id: int,
    message: str,
) -> None:
    await hub.publish(
        AgentStreamEvent(
            event="error",
            data={"message": message, "session_id": session_id},
        )
    )


async def _start_agent_run(
    payload: AgentRunRequest,
    session: AsyncSession,
) -> AgentSession:
    """Start an agent task. Live events are published to the session hub."""
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
    if _is_session_running(active_session.id):
        raise HTTPException(
            status_code=409,
            detail="An agent is already running for this session",
        )

    # Save/Update session configuration from the request
    active_session.config_id = payload.config_id
    active_session.system_prompt = payload.system_prompt
    active_session.temperature = payload.temperature
    active_session.max_tokens = payload.max_tokens
    active_session.enable_1m_context = payload.enable_1m_context
    active_session.enable_rag = payload.enable_rag
    active_session.tools = payload.tools
    active_session.mcp_servers = payload.mcp_servers
    active_session.agent_configs = payload.agent_configs
    active_session.agent_mcp_servers = payload.agent_mcp_servers
    
    # Explicitly flag JSON fields as modified to ensure SQLAlchemy persists them
    flag_modified(active_session, "tools")
    flag_modified(active_session, "mcp_servers")
    flag_modified(active_session, "agent_configs")
    flag_modified(active_session, "agent_mcp_servers")
    
    await session.commit()
    await session.refresh(active_session)
    logger.info(
        "Session %s config updated. Tools: %s, MCP: %s, Agent MCP: %s",
        active_session.id,
        active_session.tools,
        active_session.mcp_servers,
        active_session.agent_mcp_servers,
    )
    
    active_session_id = active_session.id

    result = await session.execute(
        select(LLMConfig).where(LLMConfig.id == payload.config_id)
    )
    config = result.scalars().first()
    if not config:
        raise HTTPException(status_code=404, detail="LLM config not found")
    agent_llm_configs = await _load_agent_llm_configs(payload.agent_configs, session)

    custom_agent = _get_session_agent(
        active_session=active_session,
        payload=payload,
        config=config,
        agent_configs=agent_llm_configs,
    )

    hub = _get_session_hub(active_session_id)
    hub.reset_replay()
    source_queue: asyncio.Queue[AgentStreamEvent | None] = asyncio.Queue()
    try:
        await custom_agent.start(
            source_queue,
            on_task_started=lambda task: _active_agent_tasks.__setitem__(
                active_session_id, task
            ),
            on_task_done=lambda: _active_agent_tasks.pop(active_session_id, None),
        )
    except Exception:
        _cleanup_session_hub(active_session_id)
        raise

    await hub.publish_status(is_running=True)
    asyncio.create_task(_bridge_agent_events(active_session_id, source_queue, hub))
    return active_session


async def _load_agent_llm_configs(
    agent_configs: dict[str, int | None] | None,
    session: AsyncSession,
) -> dict[str, LLMConfig]:
    if not agent_configs:
        return {}

    config_ids = {
        config_id
        for config_id in agent_configs.values()
        if isinstance(config_id, int)
    }
    if not config_ids:
        return {}

    result = await session.execute(
        select(LLMConfig).where(LLMConfig.id.in_(config_ids))
    )
    configs_by_id = {
        config.id: config
        for config in result.scalars().all()
    }
    missing_ids = sorted(config_ids - set(configs_by_id))
    if missing_ids:
        raise HTTPException(
            status_code=404,
            detail=f"Agent LLM config not found: {missing_ids[0]}",
        )

    return {
        agent_name: configs_by_id[config_id]
        for agent_name, config_id in agent_configs.items()
        if isinstance(config_id, int)
    }


async def _stop_agent_run(session_id: int) -> bool:
    """Cancel a running agent task. Returns whether a task was cancelled."""
    task = _active_agent_tasks.get(session_id)
    hub = _get_session_hub(session_id)
    if not task or task.done():
        _active_agent_tasks.pop(session_id, None)
        await hub.publish_status(is_running=False)
        _cleanup_session_hub(session_id)
        return False

    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass

    _active_agent_tasks.pop(session_id, None)
    await hub.publish_status(is_running=False)
    _cleanup_session_hub(session_id)
    return True


async def _handle_websocket_command(
    session_id: int,
    message: dict[str, Any],
    hub: SessionEventHub,
) -> None:
    command = message.get("type") or message.get("event")
    if command == "run":
        raw_payload = dict(message.get("payload") or {})
        raw_payload["session_id"] = session_id
        try:
            payload = AgentRunRequest.model_validate(raw_payload)
        except ValidationError as exc:
            await _publish_websocket_error(
                hub,
                session_id=session_id,
                message=str(exc),
            )
            if not _is_session_running(session_id):
                await hub.publish_status(is_running=False)
            return

        try:
            async with AsyncSessionLocal() as db_session:
                await _start_agent_run(payload, db_session)
        except HTTPException as exc:
            await _publish_websocket_error(
                hub,
                session_id=session_id,
                message=str(exc.detail),
            )
            if not _is_session_running(session_id):
                await hub.publish_status(is_running=False)
        except Exception as exc:
            logger.error("Failed to start websocket agent run: %s", exc)
            await _publish_websocket_error(
                hub,
                session_id=session_id,
                message=str(exc),
            )
            if not _is_session_running(session_id):
                await hub.publish_status(is_running=False)
        return

    if command == "stop":
        await _stop_agent_run(session_id)
        return

    if command == "status":
        await hub.publish_status(is_running=_is_session_running(session_id))
        return

    await _publish_websocket_error(
        hub,
        session_id=session_id,
        message=f"Unknown websocket command: {command}",
    )


@router.websocket("/sessions/{session_id}/ws")
async def session_websocket(websocket: WebSocket, session_id: int):
    """Live session channel for agent status, tool, and token events."""
    if not await _session_exists(session_id):
        await websocket.close(code=1008)
        return

    await websocket.accept()
    hub = _get_session_hub(session_id)
    queue = hub.subscribe(replay=_is_session_running(session_id))
    queue.put_nowait(
        AgentStreamEvent(
            event="status",
            data={"is_running": _is_session_running(session_id)},
        )
    )
    send_task = asyncio.create_task(_send_websocket_events(websocket, hub, queue))
    try:
        while True:
            message = await websocket.receive_json()
            if isinstance(message, dict):
                await _handle_websocket_command(session_id, message, hub)
    except WebSocketDisconnect:
        pass
    except Exception as exc:
        logger.warning("Session websocket closed with error: %s", exc)
    finally:
        send_task.cancel()
        try:
            await send_task
        except asyncio.CancelledError:
            pass
        hub.unsubscribe(queue)
        _cleanup_session_hub(session_id)


@router.post("/sessions/{session_id}/stop")
async def stop_agent(session_id: int):
    """Stop a running agent task for the given session."""
    stopped = await _stop_agent_run(session_id)
    if not stopped:
        return {"message": "No active agent task found for this session"}
    return {"message": "Agent task stopped successfully"}


@router.get("/tools", response_model=List[ToolResponse])
async def list_tools():
    """List all available tools."""
    return [
        ToolResponse(name=tool.name, description=tool.description)
        for tool in agent_tools
    ]


@router.get("/subagents", response_model=List[SubAgentResponse])
async def list_subagents():
    """List configurable specialized subagents."""
    return [
        SubAgentResponse(
            name=subagent_class.name,
            description=subagent_class.description,
        )
        for subagent_class in load_subagent_classes()
    ]


@router.get("/sessions/{session_id}/status")
async def get_session_status(session_id: int):
    """Check if an agent is currently running for this session."""
    return {"is_running": _is_session_running(session_id)}


@router.post("/run")
async def run_agent(
    payload: AgentRunRequest, session: AsyncSession = Depends(get_session)
):
    """Start an agent run. Subscribe to /sessions/{id}/ws for live events."""
    active_session = await _start_agent_run(payload, session)
    return {
        "session_id": active_session.id,
        "title": active_session.title,
        "is_running": True,
    }


@router.get("/templates", response_model=list[AgentSessionTemplateResponse])
async def list_session_templates(session: AsyncSession = Depends(get_session)):
    result = await session.execute(
        select(AgentSessionTemplate).order_by(desc(AgentSessionTemplate.updated_at))
    )
    return result.scalars().all()


@router.post("/templates", response_model=AgentSessionTemplateResponse)
async def create_session_template(
    payload: AgentSessionTemplateCreate,
    session: AsyncSession = Depends(get_session),
):
    name = payload.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Template name is required")

    template = AgentSessionTemplate(
        **payload.model_dump(exclude={"name"}),
        name=name,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    session.add(template)
    await session.commit()
    await session.refresh(template)
    return template


@router.patch("/templates/{template_id}", response_model=AgentSessionTemplateResponse)
async def update_session_template(
    template_id: int,
    payload: AgentSessionTemplateUpdate,
    session: AsyncSession = Depends(get_session),
):
    template = await session.get(AgentSessionTemplate, template_id)
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")

    update_data = payload.model_dump(exclude_unset=True)
    if "name" in update_data:
        update_data["name"] = (update_data["name"] or "").strip()
        if not update_data["name"]:
            raise HTTPException(status_code=400, detail="Template name is required")

    for key, value in update_data.items():
        setattr(template, key, value)
        if key in {"tools", "mcp_servers", "agent_configs", "agent_mcp_servers"}:
            flag_modified(template, key)

    template.updated_at = datetime.now(timezone.utc)
    await session.commit()
    await session.refresh(template)
    return template


@router.delete("/templates/{template_id}")
async def delete_session_template(
    template_id: int,
    session: AsyncSession = Depends(get_session),
):
    template = await session.get(AgentSessionTemplate, template_id)
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")

    await session.delete(template)
    await session.commit()
    return {"message": "Template deleted successfully"}


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
    title = payload.title.strip() if payload.title else "New Session"
    if not title:
        title = "New Session"

    created = AgentSession(
        title=title,
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
    if "title" in update_data:
        update_data["title"] = (update_data["title"] or "").strip()
        if not update_data["title"]:
            raise HTTPException(status_code=400, detail="Session title is required")

    for key, value in update_data.items():
        setattr(db_session, key, value)
        if key in ["tools", "mcp_servers", "agent_configs", "agent_mcp_servers"]:
            flag_modified(db_session, key)

    db_session.updated_at = datetime.now(timezone.utc)
    await session.commit()
    await session.refresh(db_session)
    logger.info(
        "Session %s patched. Tools: %s, MCP: %s, Agent MCP: %s",
        db_session.id,
        db_session.tools,
        db_session.mcp_servers,
        db_session.agent_mcp_servers,
    )
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
    messages = list(result.scalars().all())
    attach_trace_metadata_fallback(messages)
    normalize_trace_metadata(messages)
    return messages


@router.delete("/sessions/{session_id}")
async def delete_session(session_id: int, session: AsyncSession = Depends(get_session)):
    result = await session.execute(
        select(AgentSession).where(AgentSession.id == session_id)
    )
    active = result.scalars().first()
    if not active:
        raise HTTPException(status_code=404, detail="Session not found")

    await _stop_agent_run(session_id)
    hub = _session_event_hubs.pop(session_id, None)
    if hub is not None:
        await hub.close()
    _drop_session_agent(session_id)

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
    total_uncached_input_tokens = 0
    total_cached_input_tokens = 0
    total_output_tokens = 0
    rounds = []
    model_usage = {}

    round_index = 1
    for msg in db_messages:
        if msg.role == "assistant" and (msg.input_tokens or msg.output_tokens):
            usage = _token_usage_parts(
                msg.input_tokens, msg.cached_input_tokens, msg.output_tokens
            )
            it = usage["input"]
            uit = usage["uncached_input"]
            ct = usage["cached"]
            ot = usage["output"]
            total_input_tokens += it
            total_uncached_input_tokens += uit
            total_cached_input_tokens += ct
            total_output_tokens += ot

            model_name = msg.model or "unknown"
            if model_name not in model_usage:
                model_usage[model_name] = {
                    "input": 0,
                    "uncached_input": 0,
                    "cached": 0,
                    "output": 0,
                    "total": 0,
                }
            model_usage[model_name]["input"] += it
            model_usage[model_name]["uncached_input"] += uit
            model_usage[model_name]["cached"] += ct
            model_usage[model_name]["output"] += ot
            model_usage[model_name]["total"] += usage["total"]

            rounds.append(
                {
                    "step": f"Round {round_index}",
                    "tokens": usage["total"],
                    "input_tokens": it,
                    "uncached_input_tokens": uit,
                    "cached_input_tokens": ct,
                    "output_tokens": ot,
                    "model": model_name,
                    "created_at": msg.created_at.isoformat(),
                }
            )
            round_index += 1

    return {
        "total_tokens": total_input_tokens + total_output_tokens,
        "total_input_tokens": total_input_tokens,
        "total_uncached_input_tokens": total_uncached_input_tokens,
        "total_cached_input_tokens": total_cached_input_tokens,
        "total_output_tokens": total_output_tokens,
        "model_usage": model_usage,
        "rounds": rounds,
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
    total_uncached_input_tokens = 0
    total_cached_input_tokens = 0
    total_output_tokens = 0
    daily_usage = {}
    model_usage = {}

    for msg in db_messages:
        usage = _token_usage_parts(
            msg.input_tokens, msg.cached_input_tokens, msg.output_tokens
        )
        it = usage["input"]
        uit = usage["uncached_input"]
        ct = usage["cached"]
        ot = usage["output"]
        total_input_tokens += it
        total_uncached_input_tokens += uit
        total_cached_input_tokens += ct
        total_output_tokens += ot

        # Aggregate by model
        model_name = msg.model or "unknown"
        if model_name not in model_usage:
            model_usage[model_name] = {
                "input": 0,
                "uncached_input": 0,
                "cached": 0,
                "output": 0,
                "total": 0,
            }
        model_usage[model_name]["input"] += it
        model_usage[model_name]["uncached_input"] += uit
        model_usage[model_name]["cached"] += ct
        model_usage[model_name]["output"] += ot
        model_usage[model_name]["total"] += usage["total"]

        # Aggregate by date
        day = msg.created_at.date().isoformat()
        if day not in daily_usage:
            daily_usage[day] = {
                "total": 0,
                "input": 0,
                "uncached_input": 0,
                "cached": 0,
                "output": 0,
            }
        daily_usage[day]["total"] += usage["total"]
        daily_usage[day]["input"] += it
        daily_usage[day]["uncached_input"] += uit
        daily_usage[day]["cached"] += ct
        daily_usage[day]["output"] += ot

    usage_over_time = [
        {
            "date": day,
            "tokens": data["total"],
            "input_tokens": data["input"],
            "uncached_input_tokens": data["uncached_input"],
            "cached_input_tokens": data["cached"],
            "output_tokens": data["output"],
        }
        for day, data in sorted(daily_usage.items())
    ]

    return {
        "total_tokens": total_input_tokens + total_output_tokens,
        "total_input_tokens": total_input_tokens,
        "total_uncached_input_tokens": total_uncached_input_tokens,
        "total_cached_input_tokens": total_cached_input_tokens,
        "total_output_tokens": total_output_tokens,
        "model_usage": model_usage,
        "usage_over_time": usage_over_time,
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
