"""Agent session ORM models."""

from datetime import datetime, timezone

from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.orm import relationship

from server.db import Base
from server.models.llm import LLMConfig


class AgentSession(Base):
    __tablename__ = "agent_sessions"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String(255), nullable=True)
    config_id = Column(Integer, ForeignKey("llm_configs.id"), nullable=True)
    system_prompt = Column(Text, nullable=True)
    temperature = Column(Float, nullable=True)
    max_tokens = Column(Integer, nullable=True)
    enable_1m_context = Column(Boolean, nullable=True)
    enable_rag = Column(Boolean, default=False)
    tools = Column(JSON, nullable=True)
    mcp_servers = Column(JSON, nullable=True)
    agent_configs = Column(JSON, nullable=True)
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

    messages = relationship(
        "AgentMessage",
        back_populates="session",
        cascade="all, delete-orphan",
    )
    llm_config = relationship(LLMConfig)


class AgentSessionTemplate(Base):
    __tablename__ = "agent_session_templates"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False)
    config_id = Column(Integer, ForeignKey("llm_configs.id"), nullable=True)
    system_prompt = Column(Text, nullable=True)
    temperature = Column(Float, nullable=True)
    max_tokens = Column(Integer, nullable=True)
    enable_1m_context = Column(Boolean, nullable=True)
    enable_rag = Column(Boolean, default=False)
    tools = Column(JSON, nullable=True)
    mcp_servers = Column(JSON, nullable=True)
    agent_configs = Column(JSON, nullable=True)
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

    llm_config = relationship(LLMConfig)


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
