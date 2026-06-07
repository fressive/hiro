"""LLM configuration ORM model."""

from sqlalchemy import Boolean, Column, Integer, String

from server.db import Base


class LLMConfig(Base):
    __tablename__ = "llm_configs"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False)
    provider = Column(String(100), nullable=False)
    base_url = Column(String(255), nullable=True)
    api_key = Column(String(255), nullable=False)
    model = Column(String(255), nullable=False)
    enable_1m_context = Column(Boolean, default=False)
