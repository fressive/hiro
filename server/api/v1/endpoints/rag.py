"""RAG configuration and document endpoints."""

import os
import shutil
import uuid
from datetime import datetime, timezone
from typing import List
import json
import socket
import urllib.request
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, BackgroundTasks
from anyio import to_thread
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from server.db import get_session
from server.models.models import RagDocument, RagEmbeddingConfig, RagVectorStoreConfig
from server.service.rag_service import RagService
from server.models.schemas import (
    RagDocumentCreate,
    RagDocumentResponse,
    RagEmbeddingConfigUpdate,
    RagEmbeddingConfigResponse,
    RagEmbeddingTestRequest,
    RagEmbeddingTestResponse,
    RagVectorStoreConfigUpdate,
    RagVectorStoreConfigResponse,
    RagVectorStoreTestRequest,
    RagVectorStoreTestResponse,
)

router = APIRouter()

UPLOAD_DIR = "data/rag_uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)


@router.post("/upload", response_model=RagDocumentResponse)
async def upload_document(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    tags: str = Form(""),
    session: AsyncSession = Depends(get_session),
):
    """Upload a file to be used as a RAG document."""
    file_id = str(uuid.uuid4())
    ext = os.path.splitext(file.filename)[1]
    filename = f"{file_id}{ext}"
    file_path = os.path.join(UPLOAD_DIR, filename)

    try:
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Could not save file: {exc}")

    tag_list = [t.strip() for t in tags.split(",") if t.strip()]

    db_document = RagDocument(
        title=file.filename,
        source=file_path,
        tags=tag_list,
        status="queued",
        chunks=0,
        updated_at=datetime.now(timezone.utc),
    )
    session.add(db_document)
    await session.commit()
    await session.refresh(db_document)
    
    background_tasks.add_task(RagService.index_document, db_document.id)
    
    return db_document


DEFAULT_EMBEDDING_CONFIG = {
    "provider": "openai",
    "api_endpoint": "https://api.openai.com/v1",
    "model": "text-embedding-3-large",
    "dimensions": 3072,
    "chunk_size": 800,
    "chunk_overlap": 160,
    "batch_size": 64,
    "normalize": True,
}

DEFAULT_VECTOR_STORE_CONFIG = {
    "provider": "milvus",
    "data_source": "local",
    "endpoint": None,
    "token": None,
    "db_name": None,
    "collection_name": "hiro_documents",
}


@router.get("/documents", response_model=List[RagDocumentResponse])
async def list_documents(session: AsyncSession = Depends(get_session)):
    """List all RAG documents."""
    result = await session.execute(select(RagDocument).order_by(RagDocument.id.desc()))
    return result.scalars().all()


@router.post("/documents", response_model=RagDocumentResponse)
async def create_document(
    payload: RagDocumentCreate, 
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_session)
):
    """Create a new RAG document."""
    db_document = RagDocument(
        title=payload.title,
        source=payload.source,
        tags=payload.tags,
        status="queued",
        chunks=0,
        updated_at=datetime.now(timezone.utc),
    )
    session.add(db_document)
    await session.commit()
    await session.refresh(db_document)
    
    background_tasks.add_task(RagService.index_document, db_document.id)
    
    return db_document


@router.get("/documents/{document_id}", response_model=RagDocumentResponse)
async def get_document(
    document_id: int, session: AsyncSession = Depends(get_session)
):
    """Get details of a single RAG document."""
    result = await session.execute(
        select(RagDocument).where(RagDocument.id == document_id)
    )
    db_document = result.scalars().first()
    if not db_document:
        raise HTTPException(status_code=404, detail="Document not found")
    return db_document


@router.get("/documents/{document_id}/chunks")
async def get_document_chunks(
    document_id: int, session: AsyncSession = Depends(get_session)
):
    """Get indexed chunks of a RAG document."""
    result = await session.execute(
        select(RagDocument).where(RagDocument.id == document_id)
    )
    db_document = result.scalars().first()
    if not db_document:
        raise HTTPException(status_code=404, detail="Document not found")
    
    chunks = await RagService.get_document_chunks(document_id)
    return chunks


@router.delete("/documents/{document_id}")
async def delete_document(
    document_id: int, 
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_session)
):
    """Delete a RAG document."""
    result = await session.execute(
        select(RagDocument).where(RagDocument.id == document_id)
    )
    db_document = result.scalars().first()
    if not db_document:
        raise HTTPException(status_code=404, detail="Document not found")

    # Schedule deletion of vector data and local file
    background_tasks.add_task(RagService.delete_document_data, db_document.id, db_document.source)

    await session.delete(db_document)
    await session.commit()
    return {"message": "Document deleted successfully"}


@router.post("/documents/{document_id}/reindex", response_model=RagDocumentResponse)
async def reindex_document(
    document_id: int,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_session)
):
    """Trigger re-indexing for a specific document."""
    result = await session.execute(
        select(RagDocument).where(RagDocument.id == document_id)
    )
    db_document = result.scalars().first()
    if not db_document:
        raise HTTPException(status_code=404, detail="Document not found")

    db_document.status = "queued"
    await session.commit()
    await session.refresh(db_document)

    background_tasks.add_task(RagService.index_document, db_document.id)

    return db_document


@router.get("/embedding-config", response_model=RagEmbeddingConfigResponse)
async def get_embedding_config(session: AsyncSession = Depends(get_session)):
    """Get the RAG embedding configuration."""
    result = await session.execute(select(RagEmbeddingConfig))
    db_config = result.scalars().first()

    if not db_config:
        db_config = RagEmbeddingConfig(**DEFAULT_EMBEDDING_CONFIG)
        session.add(db_config)
        await session.commit()
        await session.refresh(db_config)

    return RagEmbeddingConfigResponse(
        id=db_config.id,
        provider=db_config.provider,
        api_endpoint=db_config.api_endpoint,
        model=db_config.model,
        dimensions=db_config.dimensions,
        chunk_size=db_config.chunk_size,
        chunk_overlap=db_config.chunk_overlap,
        batch_size=db_config.batch_size,
        normalize=db_config.normalize,
        has_token=bool(db_config.api_token),
    )


@router.put("/embedding-config", response_model=RagEmbeddingConfigResponse)
async def update_embedding_config(
    payload: RagEmbeddingConfigUpdate, session: AsyncSession = Depends(get_session)
):
    """Update the RAG embedding configuration."""
    result = await session.execute(select(RagEmbeddingConfig))
    db_config = result.scalars().first()

    if not db_config:
        db_config = RagEmbeddingConfig(**DEFAULT_EMBEDDING_CONFIG)
        session.add(db_config)
        await session.flush()

    update_data = payload.dict(exclude_unset=True)
    api_token = update_data.pop("api_token", None)

    for key, value in update_data.items():
        setattr(db_config, key, value)

    if api_token is not None:
        db_config.api_token = api_token or None

    await session.commit()
    await session.refresh(db_config)

    return RagEmbeddingConfigResponse(
        id=db_config.id,
        provider=db_config.provider,
        api_endpoint=db_config.api_endpoint,
        model=db_config.model,
        dimensions=db_config.dimensions,
        chunk_size=db_config.chunk_size,
        chunk_overlap=db_config.chunk_overlap,
        batch_size=db_config.batch_size,
        normalize=db_config.normalize,
        has_token=bool(db_config.api_token),
    )


@router.post("/embedding-config/test", response_model=RagEmbeddingTestResponse)
async def test_embedding_config(
    payload: RagEmbeddingTestRequest, session: AsyncSession = Depends(get_session)
):
    """Test the RAG embedding configuration input."""
    result = await session.execute(select(RagEmbeddingConfig))
    db_config = result.scalars().first()

    provider = payload.provider or (db_config.provider if db_config else DEFAULT_EMBEDDING_CONFIG["provider"])
    model = payload.model or (db_config.model if db_config else DEFAULT_EMBEDDING_CONFIG["model"])
    api_endpoint = payload.api_endpoint or (
        db_config.api_endpoint if db_config else DEFAULT_EMBEDDING_CONFIG["api_endpoint"]
    )
    api_token = payload.api_token or (db_config.api_token if db_config else None)

    if not provider or not model or not api_endpoint:
        return RagEmbeddingTestResponse(
            success=False, message="Provider, model, and endpoint are required."
        )

    if provider.lower() in {"openai", "cohere"} and not api_token:
        return RagEmbeddingTestResponse(
            success=False, message="API token is required for hosted providers."
        )

    try:
        vector: List[float]

        if provider.lower() == "openai":
            from langchain_openai import OpenAIEmbeddings

            try:
                embeddings = OpenAIEmbeddings(
                    api_key=api_token,
                    base_url=api_endpoint,
                    model=model,
                )
            except TypeError:
                embeddings = OpenAIEmbeddings(
                    openai_api_key=api_token,
                    base_url=api_endpoint,
                    model=model,
                )

            vector = await to_thread.run_sync(embeddings.embed_query, "hiro")
        elif provider.lower() == "cohere":
            try:
                from langchain_cohere import CohereEmbeddings
            except ImportError as exc:
                raise RuntimeError(
                    "Cohere embeddings are not installed on the server."
                ) from exc

            embeddings = CohereEmbeddings(
                cohere_api_key=api_token,
                model=model,
                base_url=api_endpoint,
            )
            vector = await to_thread.run_sync(embeddings.embed_query, "hiro")
        elif provider.lower() == "ollama":
            def _ollama_embed() -> List[float]:
                base = api_endpoint.rstrip("/")
                url = f"{base}/api/embed"
                
                payload = json.dumps({"model": model, "prompt": "hiro"}).encode("utf-8")
                request = urllib.request.Request(
                    url,
                    data=payload,
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urllib.request.urlopen(request, timeout=15) as response:
                    data = json.loads(response.read().decode("utf-8"))
                embedding = data.get("embedding")
                if embedding is None:
                    raise RuntimeError("Ollama response missing embedding field.")
                return embedding

            vector = await to_thread.run_sync(_ollama_embed)
        else:
            raise RuntimeError("Embedding test not implemented for this provider.")

        if not isinstance(vector, list) or not vector:
            return RagEmbeddingTestResponse(
                success=False,
                message="Embedding output is empty or invalid.",
            )

        if not all(isinstance(value, (float, int)) for value in vector):
            return RagEmbeddingTestResponse(
                success=False,
                message="Embedding output contains non-numeric values.",
            ) 

        return RagEmbeddingTestResponse(
            success=True,
            message=f"Embedding output OK. Dimension: {len(vector)}",
        )
    except Exception as exc:
        return RagEmbeddingTestResponse(success=False, message=str(exc))


@router.get("/vector-store-config", response_model=RagVectorStoreConfigResponse)
async def get_vector_store_config(session: AsyncSession = Depends(get_session)):
    """Get the RAG vector store configuration."""
    result = await session.execute(select(RagVectorStoreConfig))
    db_config = result.scalars().first()

    if not db_config:
        db_config = RagVectorStoreConfig(**DEFAULT_VECTOR_STORE_CONFIG)
        session.add(db_config)
        await session.commit()
        await session.refresh(db_config)

    return RagVectorStoreConfigResponse(
        id=db_config.id,
        provider=db_config.provider,
        data_source=db_config.data_source,
        endpoint=db_config.endpoint,
        db_name=db_config.db_name,
        collection_name=db_config.collection_name,
        has_token=bool(db_config.token),
    )


@router.put("/vector-store-config", response_model=RagVectorStoreConfigResponse)
async def update_vector_store_config(
    payload: RagVectorStoreConfigUpdate, session: AsyncSession = Depends(get_session)
):
    """Update the RAG vector store configuration."""
    result = await session.execute(select(RagVectorStoreConfig))
    db_config = result.scalars().first()

    if not db_config:
        db_config = RagVectorStoreConfig(**DEFAULT_VECTOR_STORE_CONFIG)
        session.add(db_config)
        await session.flush()

    update_data = payload.dict(exclude_unset=True)
    token = update_data.pop("token", None)

    for key, value in update_data.items():
        setattr(db_config, key, value)

    if token is not None:
        db_config.token = token or None

    if db_config.data_source == "remote":
        if not db_config.endpoint or not db_config.db_name:
            raise HTTPException(
                status_code=400,
                detail="Remote data source requires endpoint and db_name.",
            )

    await session.commit()
    await session.refresh(db_config)

    return RagVectorStoreConfigResponse(
        id=db_config.id,
        provider=db_config.provider,
        data_source=db_config.data_source,
        endpoint=db_config.endpoint,
        db_name=db_config.db_name,
        collection_name=db_config.collection_name,
        has_token=bool(db_config.token),
    )


@router.post("/vector-store-config/test", response_model=RagVectorStoreTestResponse)
async def test_vector_store_config(
    payload: RagVectorStoreTestRequest, session: AsyncSession = Depends(get_session)
):
    """Test the vector store configuration input."""
    result = await session.execute(select(RagVectorStoreConfig))
    db_config = result.scalars().first()

    provider = payload.provider or (db_config.provider if db_config else DEFAULT_VECTOR_STORE_CONFIG["provider"])
    data_source = payload.data_source or (
        db_config.data_source if db_config else DEFAULT_VECTOR_STORE_CONFIG["data_source"]
    )
    endpoint = payload.endpoint or (db_config.endpoint if db_config else None)
    db_name = payload.db_name or (db_config.db_name if db_config else None)
    token = payload.token or (db_config.token if db_config else None)

    if provider.lower() != "milvus":
        return RagVectorStoreTestResponse(
            success=False,
            message="Only Milvus is supported for vector store testing.",
        )

    if data_source == "local":
        return RagVectorStoreTestResponse(
            success=True,
            message="Local mode configured. Remote connectivity test skipped.",
        )

    if not endpoint or not db_name:
        return RagVectorStoreTestResponse(
            success=False,
            message="Remote data source requires endpoint and db_name.",
        )

    parsed = urlparse(endpoint if "://" in endpoint else f"http://{endpoint}")
    host = parsed.hostname
    port = parsed.port or 19530
    if not host:
        return RagVectorStoreTestResponse(
            success=False,
            message="Endpoint is invalid or missing host.",
        )

    try:
        with socket.create_connection((host, port), timeout=5):
            pass
    except OSError as exc:
        return RagVectorStoreTestResponse(success=False, message=str(exc))

    token_verified = False

    if token:
        try:
            from pymilvus import MilvusClient
        except ImportError as exc:
            return RagVectorStoreTestResponse(
                success=False,
                message="pymilvus is not installed; cannot verify token.",
            )

        try:
            uri = endpoint if "://" in endpoint else f"http://{endpoint}"
            client = MilvusClient(uri=uri, token=token, db_name=db_name or None)
            client.list_collections()
            client.close()
            token_verified = True
        except Exception as exc:
            return RagVectorStoreTestResponse(success=False, message=str(exc))

    message = f"Connected to {host}:{port} (db: {db_name})."
    if token and token_verified:
        message = f"{message} Token verified."

    return RagVectorStoreTestResponse(success=True, message=message)
