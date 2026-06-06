"""MCP configuration endpoints."""

from datetime import datetime, timezone
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from server.db import get_session
from server.models.models import MCPServerConfig
from server.models.schemas import (
    MCPServerConfigCreate,
    MCPServerConfigUpdate,
    MCPServerConfigResponse,
    MCPTestRequest,
    MCPTestResponse,
)
from server.service.mcp_service import McpService
from contextlib import AsyncExitStack

router = APIRouter()


@router.post("/test", response_model=MCPTestResponse)
async def test_mcp_server(payload: MCPTestRequest):
    """Test connection to an MCP server."""
    async with AsyncExitStack() as exit_stack:
        try:
            # Create a temporary config object for McpService
            config = MCPServerConfig(
                name=payload.name or "test-server",
                type=payload.type,
                command=payload.command,
                args=payload.args,
                env=payload.env,
                url=payload.url
            )
            
            tools = await McpService.load_mcp_tools([config], exit_stack)
            tool_names = [t.name for t in tools]
            
            return MCPTestResponse(
                success=True,
                message=f"Successfully connected and loaded {len(tool_names)} tools.",
                tools=tool_names
            )
        except Exception as e:
            return MCPTestResponse(
                success=False,
                message=f"Failed to connect: {str(e)}"
            )


@router.get("/", response_model=List[MCPServerConfigResponse])
async def list_mcp_servers(session: AsyncSession = Depends(get_session)):
    """List all MCP server configurations."""
    result = await session.execute(select(MCPServerConfig).order_by(MCPServerConfig.id.desc()))
    return result.scalars().all()


@router.post("/", response_model=MCPServerConfigResponse)
async def create_mcp_server(
    payload: MCPServerConfigCreate, session: AsyncSession = Depends(get_session)
):
    """Create a new MCP server configuration."""
    # Check if name already exists
    existing = await session.execute(
        select(MCPServerConfig).where(MCPServerConfig.name == payload.name)
    )
    if existing.scalars().first():
        raise HTTPException(status_code=400, detail=f"MCP server with name '{payload.name}' already exists.")

    db_config = MCPServerConfig(
        name=payload.name,
        type=payload.type,
        command=payload.command,
        args=payload.args,
        env=payload.env,
        url=payload.url,
        enabled=payload.enabled if payload.enabled is not None else True,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    session.add(db_config)
    await session.commit()
    await session.refresh(db_config)
    return db_config


@router.get("/{server_id}", response_model=MCPServerConfigResponse)
async def get_mcp_server(
    server_id: int, session: AsyncSession = Depends(get_session)
):
    """Get details of a single MCP server configuration."""
    result = await session.execute(
        select(MCPServerConfig).where(MCPServerConfig.id == server_id)
    )
    db_config = result.scalars().first()
    if not db_config:
        raise HTTPException(status_code=404, detail="MCP server configuration not found")
    return db_config


@router.put("/{server_id}", response_model=MCPServerConfigResponse)
async def update_mcp_server(
    server_id: int,
    payload: MCPServerConfigUpdate,
    session: AsyncSession = Depends(get_session),
):
    """Update an MCP server configuration."""
    result = await session.execute(
        select(MCPServerConfig).where(MCPServerConfig.id == server_id)
    )
    db_config = result.scalars().first()
    if not db_config:
        raise HTTPException(status_code=404, detail="MCP server configuration not found")

    update_data = payload.dict(exclude_unset=True)
    
    # Check name uniqueness if changed
    if "name" in update_data and update_data["name"] != db_config.name:
        existing = await session.execute(
            select(MCPServerConfig).where(MCPServerConfig.name == update_data["name"])
        )
        if existing.scalars().first():
            raise HTTPException(status_code=400, detail=f"MCP server with name '{update_data['name']}' already exists.")

    for key, value in update_data.items():
        setattr(db_config, key, value)

    db_config.updated_at = datetime.now(timezone.utc)
    await session.commit()
    await session.refresh(db_config)
    return db_config


@router.delete("/{server_id}")
async def delete_mcp_server(
    server_id: int, session: AsyncSession = Depends(get_session)
):
    """Delete an MCP server configuration."""
    result = await session.execute(
        select(MCPServerConfig).where(MCPServerConfig.id == server_id)
    )
    db_config = result.scalars().first()
    if not db_config:
        raise HTTPException(status_code=404, detail="MCP server configuration not found")

    await session.delete(db_config)
    await session.commit()
    return {"message": "MCP server configuration deleted successfully"}
