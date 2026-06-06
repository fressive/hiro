"""SQLAlchemy ORM models."""

from sqlalchemy import Column, Integer, String, Text, DateTime, Boolean, JSON, ForeignKey, Float
from sqlalchemy.orm import relationship
from datetime import datetime, timezone

from server.db import Base


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(150), unique=True, index=True, nullable=False)
    email = Column(String(255), nullable=True)
    hashed_password = Column(String(255), nullable=False)


class Item(Base):
    __tablename__ = "items"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)


class LLMConfig(Base):
    __tablename__ = "llm_configs"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False)
    provider = Column(String(100), nullable=False)
    base_url = Column(String(255), nullable=True)
    api_key = Column(String(255), nullable=False)
    model = Column(String(255), nullable=False)
    enable_1m_context = Column(Boolean, default=False)


class RagDocument(Base):
    __tablename__ = "rag_documents"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String(255), nullable=False)
    source = Column(Text, nullable=False)
    status = Column(String(50), nullable=False, default="queued")
    chunks = Column(Integer, nullable=False, default=0)
    tags = Column(JSON, nullable=False, default=list)
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )


class RagEmbeddingConfig(Base):
    __tablename__ = "rag_embedding_configs"

    id = Column(Integer, primary_key=True, index=True)
    provider = Column(String(100), nullable=False, default="openai")
    api_endpoint = Column(String(255), nullable=False, default="https://api.openai.com/v1")
    api_token = Column(String(255), nullable=True)
    model = Column(String(255), nullable=False, default="text-embedding-3-large")
    dimensions = Column(Integer, nullable=False, default=3072)
    chunk_size = Column(Integer, nullable=False, default=800)
    chunk_overlap = Column(Integer, nullable=False, default=160)
    batch_size = Column(Integer, nullable=False, default=64)
    normalize = Column(Boolean, nullable=False, default=True)


class RagVectorStoreConfig(Base):
    __tablename__ = "rag_vector_store_configs"

    id = Column(Integer, primary_key=True, index=True)
    provider = Column(String(100), nullable=False, default="milvus")
    data_source = Column(String(50), nullable=False, default="local")
    endpoint = Column(String(255), nullable=True)
    token = Column(String(255), nullable=True)
    db_name = Column(String(255), nullable=True)
    collection_name = Column(String(255), nullable=False, default="hiro_documents")


class AgentSession(Base):
    __tablename__ = "agent_sessions"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String(255), nullable=True)
    config_id = Column(Integer, ForeignKey("llm_configs.id"), nullable=True)
    system_prompt = Column(Text, nullable=True)
    temperature = Column(Float, nullable=True)
    max_tokens = Column(Integer, nullable=True)
    enable_1m_context = Column(Boolean, nullable=True)
    is_deep_agent = Column(Boolean, nullable=True)
    enable_rag = Column(Boolean, default=False)
    tools = Column(JSON, nullable=True)
    mcp_servers = Column(JSON, nullable=True)
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    messages = relationship("AgentMessage", back_populates="session", cascade="all, delete-orphan")
    llm_config = relationship("LLMConfig")


class AgentMessage(Base):
    __tablename__ = "agent_messages"

    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(Integer, ForeignKey("agent_sessions.id"), index=True, nullable=False)
    role = Column(String(50), nullable=False)
    content = Column(Text, nullable=False)
    name = Column(String(100), nullable=True)
    tool_call_id = Column(String(100), nullable=True)
    tool_calls = Column(JSON, nullable=True)
    extra_metadata = Column(JSON, nullable=True)
    input_tokens = Column(Integer, nullable=True)
    cached_input_tokens = Column(Integer, nullable=True)
    output_tokens = Column(Integer, nullable=True)
    model = Column(String(255), nullable=True)
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    
    session = relationship("AgentSession", back_populates="messages")


class MCPServerConfig(Base):
    __tablename__ = "mcp_server_configs"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), unique=True, index=True, nullable=False)
    type = Column(String(50), nullable=False, default="command")  # command, sse, or streamable-http
    command = Column(String(255), nullable=True)
    args = Column(JSON, nullable=True)
    env = Column(JSON, nullable=True)
    url = Column(String(255), nullable=True)
    enabled = Column(Boolean, default=True)
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )


class APIToken(Base):
    __tablename__ = "api_tokens"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False)
    hashed_token = Column(String(255), unique=True, index=True, nullable=False)
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    last_used_at = Column(DateTime(timezone=True), nullable=True)
