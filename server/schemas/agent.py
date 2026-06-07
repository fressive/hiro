"""Agent session schemas."""

from datetime import datetime
from typing import Dict, List, Optional

from pydantic import BaseModel, Field


class AgentRunRequest(BaseModel):
    """Agent run request schema."""

    config_id: int
    input: str
    session_id: Optional[int] = None
    system_prompt: Optional[str] = None
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None
    enable_1m_context: Optional[bool] = None
    is_deep_agent: Optional[bool] = True
    enable_rag: Optional[bool] = False
    tools: Optional[List[str]] = None
    mcp_servers: Optional[List[str]] = None
    agent_configs: Optional[Dict[str, Optional[int]]] = None


class ToolResponse(BaseModel):
    """Tool information response schema."""

    name: str
    description: str


class AgentGraphNodeResponse(BaseModel):
    """Execution graph node metadata."""

    id: str
    label: str
    description: Optional[str] = None
    status: Optional[str] = None
    optional: Optional[bool] = None
    node_type: Optional[str] = None
    agent_name: Optional[str] = None


class AgentGraphEdgeResponse(BaseModel):
    """Execution graph edge metadata."""

    from_: str = Field(alias="from")
    to: str
    condition: Optional[str] = None
    bidirectional: Optional[bool] = None


class AgentGraphResponse(BaseModel):
    """Execution graph metadata response schema."""

    nodes: List[AgentGraphNodeResponse]
    edges: List[AgentGraphEdgeResponse]


class AgentSessionCreate(BaseModel):
    """Agent session creation schema."""

    title: Optional[str] = None


class AgentSessionUpdate(BaseModel):
    """Agent session update schema."""

    title: Optional[str] = None
    config_id: Optional[int] = None
    system_prompt: Optional[str] = None
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None
    enable_1m_context: Optional[bool] = None
    is_deep_agent: Optional[bool] = None
    enable_rag: Optional[bool] = None
    tools: Optional[List[str]] = None
    mcp_servers: Optional[List[str]] = None
    agent_configs: Optional[Dict[str, Optional[int]]] = None


class AgentSessionResponse(BaseModel):
    """Agent session response schema."""

    id: int
    title: Optional[str] = None
    config_id: Optional[int] = None
    system_prompt: Optional[str] = None
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None
    enable_1m_context: Optional[bool] = None
    is_deep_agent: Optional[bool] = None
    enable_rag: Optional[bool] = False
    tools: Optional[List[str]] = None
    mcp_servers: Optional[List[str]] = None
    agent_configs: Optional[Dict[str, Optional[int]]] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class AgentSessionTemplateCreate(BaseModel):
    """Agent session settings template creation schema."""

    name: str
    config_id: Optional[int] = None
    system_prompt: Optional[str] = None
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None
    enable_1m_context: Optional[bool] = None
    is_deep_agent: Optional[bool] = None
    enable_rag: Optional[bool] = None
    tools: Optional[List[str]] = None
    mcp_servers: Optional[List[str]] = None
    agent_configs: Optional[Dict[str, Optional[int]]] = None


class AgentSessionTemplateUpdate(BaseModel):
    """Agent session settings template update schema."""

    name: Optional[str] = None
    config_id: Optional[int] = None
    system_prompt: Optional[str] = None
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None
    enable_1m_context: Optional[bool] = None
    is_deep_agent: Optional[bool] = None
    enable_rag: Optional[bool] = None
    tools: Optional[List[str]] = None
    mcp_servers: Optional[List[str]] = None
    agent_configs: Optional[Dict[str, Optional[int]]] = None


class AgentSessionTemplateResponse(BaseModel):
    """Agent session settings template response schema."""

    id: int
    name: str
    config_id: Optional[int] = None
    system_prompt: Optional[str] = None
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None
    enable_1m_context: Optional[bool] = None
    is_deep_agent: Optional[bool] = None
    enable_rag: Optional[bool] = False
    tools: Optional[List[str]] = None
    mcp_servers: Optional[List[str]] = None
    agent_configs: Optional[Dict[str, Optional[int]]] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class AgentMessageResponse(BaseModel):
    """Agent message response schema."""

    id: int
    session_id: int
    role: str
    content: str
    name: Optional[str] = None
    tool_call_id: Optional[str] = None
    tool_calls: Optional[List[dict]] = None
    extra_metadata: Optional[dict] = None
    input_tokens: Optional[int] = None
    cached_input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None
    model: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True


class SessionFileResponse(BaseModel):
    """Session file response schema."""

    path: str
    size: int
    modified_at: datetime
    type: str  # "file" or "directory"
