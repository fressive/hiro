"""MCP server configuration ORM model."""

from datetime import datetime, timezone

from sqlalchemy import Boolean, Column, DateTime, Integer, JSON, String

from server.db import Base


class MCPServerConfig(Base):
    __tablename__ = "mcp_server_configs"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), unique=True, index=True, nullable=False)
    type = Column(String(50), nullable=False, default="command")
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
