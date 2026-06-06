"""Pydantic schemas for request/response validation."""

from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime


class TokenResponse(BaseModel):
    """Token response schema."""

    access_token: str
    token_type: str = "bearer"


class UserBase(BaseModel):
    """Base user schema."""

    username: str
    email: Optional[str] = None


class UserCreate(UserBase):
    """User creation schema."""

    password: str = Field(..., max_length=72)


class UserResponse(UserBase):
    """User response schema."""

    id: Optional[int] = None

    class Config:
        from_attributes = True


class ItemBase(BaseModel):
    """Base item schema."""

    name: str
    description: Optional[str] = None


class ItemCreate(ItemBase):
    """Item creation schema."""

    pass


class ItemResponse(ItemBase):
    """Item response schema."""

    id: Optional[int] = None

    class Config:
        from_attributes = True


class InstallationStatusResponse(BaseModel):
    """Installation status response schema."""

    installed: bool

class InstallationRequest(BaseModel):
    """Application installation request schema."""

    database_url: str
    admin_username: str
    admin_email: Optional[str] = None
    admin_password: str = Field(..., max_length=72)


class InstallationResponse(BaseModel):
    """Application installation response schema."""

    installed: bool
    message: str


class DatabaseCheckRequest(BaseModel):
    """Database connection check request schema."""

    database_url: str


class DatabaseCheckResponse(BaseModel):
    """Database connection check response schema."""

    success: bool
    message: str


class SystemCheckItem(BaseModel):
    """System check item schema."""

    name: str
    exists: bool
    message: Optional[str] = None


class SystemCheckResponse(BaseModel):
    """System check response schema."""

    success: bool
    items: List[SystemCheckItem]


class LLMConfigBase(BaseModel):
    """Base LLM configuration schema."""

    name: str
    provider: str
    base_url: Optional[str] = None
    api_key: str
    model: str
    enable_1m_context: Optional[bool] = False


class LLMConfigCreate(LLMConfigBase):
    """LLM configuration creation schema."""

    pass


class LLMConfigUpdate(BaseModel):
    """LLM configuration update schema."""

    name: Optional[str] = None
    provider: Optional[str] = None
    base_url: Optional[str] = None
    api_key: Optional[str] = None
    model: Optional[str] = None
    enable_1m_context: Optional[bool] = None


class LLMConfigResponse(BaseModel):
    """LLM configuration response schema."""

    id: int
    name: str
    provider: str
    base_url: Optional[str] = None
    model: str
    enable_1m_context: bool

    class Config:
        from_attributes = True


class LLMTestRequest(BaseModel):
    """LLM test request schema."""

    id: Optional[int] = None
    name: Optional[str] = None
    provider: str
    base_url: Optional[str] = None
    api_key: Optional[str] = None
    model: str
    enable_1m_context: Optional[bool] = None


class LLMTestResponse(BaseModel):
    """LLM test response schema."""

    success: bool
    message: str


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


class ToolResponse(BaseModel):
    """Tool information response schema."""

    name: str
    description: str


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
    output_tokens: Optional[int] = None
    model: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True


class RagDocumentBase(BaseModel):
    """Base RAG document schema."""

    title: str
    source: str
    tags: List[str] = Field(default_factory=list)


class RagDocumentCreate(RagDocumentBase):
    """RAG document creation schema."""

    pass


class RagDocumentResponse(RagDocumentBase):
    """RAG document response schema."""

    id: int
    status: str
    chunks: int
    updated_at: datetime

    class Config:
        from_attributes = True


class RagEmbeddingConfigUpdate(BaseModel):
    """RAG embedding configuration update schema."""

    provider: Optional[str] = None
    api_endpoint: Optional[str] = None
    api_token: Optional[str] = None
    model: Optional[str] = None
    dimensions: Optional[int] = None
    chunk_size: Optional[int] = None
    chunk_overlap: Optional[int] = None
    batch_size: Optional[int] = None
    normalize: Optional[bool] = None


class RagEmbeddingConfigResponse(BaseModel):
    """RAG embedding configuration response schema."""

    id: int
    provider: str
    api_endpoint: str
    model: str
    dimensions: int
    chunk_size: int
    chunk_overlap: int
    batch_size: int
    normalize: bool
    has_token: bool

    class Config:
        from_attributes = True


class RagEmbeddingTestRequest(BaseModel):
    """RAG embedding test request schema."""

    provider: Optional[str] = None
    api_endpoint: Optional[str] = None
    api_token: Optional[str] = None
    model: Optional[str] = None


class RagEmbeddingTestResponse(BaseModel):
    """RAG embedding test response schema."""

    success: bool
    message: str


class RagVectorStoreConfigUpdate(BaseModel):
    """RAG vector store configuration update schema."""

    provider: Optional[str] = None
    data_source: Optional[str] = None
    endpoint: Optional[str] = None
    token: Optional[str] = None
    db_name: Optional[str] = None
    collection_name: Optional[str] = None


class RagVectorStoreConfigResponse(BaseModel):
    """RAG vector store configuration response schema."""

    id: int
    provider: str
    data_source: str
    endpoint: Optional[str] = None
    db_name: Optional[str] = None
    collection_name: str
    has_token: bool

    class Config:
        from_attributes = True


class RagVectorStoreTestRequest(BaseModel):
    """RAG vector store test request schema."""

    provider: Optional[str] = None
    data_source: Optional[str] = None
    endpoint: Optional[str] = None
    token: Optional[str] = None
    db_name: Optional[str] = None
    collection_name: Optional[str] = None


class RagVectorStoreTestResponse(BaseModel):
    """RAG vector store test response schema."""

    success: bool
    message: str


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


class APITokenBase(BaseModel):
    """Base API token schema."""

    name: str


class APITokenCreate(APITokenBase):
    """API token creation schema."""

    pass


class APITokenResponse(APITokenBase):
    """API token response schema (for listing)."""

    id: int
    created_at: datetime
    last_used_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class APITokenCreated(APITokenResponse):
    """API token response schema (returned only once upon creation)."""

    token: str


class SessionFileResponse(BaseModel):
    """Session file response schema."""

    path: str
    size: int
    modified_at: datetime
    type: str  # "file" or "directory"
