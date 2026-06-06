"""MCP server schemas."""

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel


class MCPServerConfigBase(BaseModel):
    """Base MCP server configuration schema."""

    name: str
    type: str = "command"
    command: Optional[str] = None
    args: Optional[List[str]] = None
    env: Optional[dict] = None
    url: Optional[str] = None
    enabled: Optional[bool] = True


class MCPServerConfigCreate(MCPServerConfigBase):
    """MCP server configuration creation schema."""

    pass


class MCPServerConfigUpdate(BaseModel):
    """MCP server configuration update schema."""

    name: Optional[str] = None
    type: Optional[str] = None
    command: Optional[str] = None
    args: Optional[List[str]] = None
    env: Optional[dict] = None
    url: Optional[str] = None
    enabled: Optional[bool] = None


class MCPServerConfigResponse(MCPServerConfigBase):
    """MCP server configuration response schema."""

    id: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class MCPTestRequest(BaseModel):
    """MCP server test request schema."""

    name: Optional[str] = None
    type: str = "command"
    command: Optional[str] = None
    args: Optional[List[str]] = None
    env: Optional[dict] = None
    url: Optional[str] = None


class MCPTestResponse(BaseModel):
    """MCP server test response schema."""

    success: bool
    message: str
    tools: Optional[List[str]] = None
