"""API token ORM model."""

from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, Integer, String

from server.db import Base


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
