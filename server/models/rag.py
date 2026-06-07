"""RAG ORM models."""

from datetime import datetime, timezone

from sqlalchemy import Boolean, Column, DateTime, Integer, JSON, String, Text

from server.db import Base


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
