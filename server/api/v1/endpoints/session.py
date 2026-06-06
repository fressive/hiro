"""Agent API endpoints."""

import asyncio
import os
import shutil
from pathlib import Path
from datetime import datetime, timezone
from typing import List

from fastapi import APIRouter, Depends, HTTPException, File, UploadFile
from fastapi.responses import StreamingResponse, FileResponse
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from server.agent.custom_agent import (
    CustomAgent,
    _add_token_usage,
    _llm_result_token_usage,
    _message_token_usage,
    _normalize_token_usage,
    _stream_text_segments,
    _subtract_token_usage,
)
from server.agent.tools import agent_tools
from server.db import get_session
from server.models.models import LLMConfig, AgentSession, AgentMessage
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

    custom_agent = CustomAgent(
        session_id=active_session_id,
        session_title=active_session.title,
        payload=payload,
        config=config,
    )

    return StreamingResponse(
        custom_agent.stream(
            on_task_started=lambda task: _active_agent_tasks.__setitem__(
                active_session_id, task
            ),
            on_task_done=lambda: _active_agent_tasks.pop(active_session_id, None),
        ),
        media_type="text/event-stream",
    )


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
