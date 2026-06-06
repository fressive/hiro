"""RAG schemas."""

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field


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
