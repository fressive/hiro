"""RAG service for document indexing and retrieval."""

import os
import logging
from typing import List, Any
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_core.documents import Document

from server.models.rag import RagDocument, RagEmbeddingConfig, RagVectorStoreConfig
from server.db import AsyncSessionLocal

logger = logging.getLogger(__name__)


class RagService:
    """Service for RAG operations."""

    @staticmethod
    async def index_document(document_id: int):
        """Extract text, chunk, embed, and store a document."""
        async with AsyncSessionLocal() as session:
            # 1. Fetch document and configs
            result = await session.execute(
                select(RagDocument).where(RagDocument.id == document_id)
            )
            db_document = result.scalars().first()
            if not db_document:
                logger.error(f"Document {document_id} not found for indexing")
                return

            try:
                db_document.status = "processing"
                await session.commit()

                # Get configs
                embed_result = await session.execute(select(RagEmbeddingConfig))
                embed_config = embed_result.scalars().first()
                
                vector_result = await session.execute(select(RagVectorStoreConfig))
                vector_config = vector_result.scalars().first()

                if not embed_config or not vector_config:
                    raise RuntimeError("Embedding or Vector Store configuration missing")

                # 2. Load documents
                documents = await RagService._load_documents(db_document.source)
                if not documents:
                    raise RuntimeError("No documents loaded from source")

                # 3. Chunk documents
                chunks = RagService._chunk_documents(documents, embed_config)
                db_document.chunks = len(chunks)
                await session.commit()

                # 4. Generate embeddings and store
                await RagService._store_in_vector_db(chunks, db_document, embed_config, vector_config)

                # 5. Update status
                db_document.status = "indexed"
                db_document.updated_at = datetime.now(timezone.utc)
                await session.commit()
                logger.info(f"Successfully indexed document {document_id}")

            except Exception as exc:
                logger.exception(f"Failed to index document {document_id}: {exc}")
                db_document.status = "error"
                await session.commit()

    @staticmethod
    async def _load_documents(source: str) -> List[Document]:
        """Load documents from various source types using LangChain community loaders."""
        if source.startswith("http"):
            # TODO: Implement WebBaseLoader or similar
            return []
        
        if not os.path.exists(source):
            logger.error(f"Source file not found: {source}")
            return []

        ext = os.path.splitext(source)[1].lower()
        
        try:
            from anyio import to_thread
            
            if ext in [".txt", ".md"]:
                from langchain_community.document_loaders import TextLoader
                loader = TextLoader(source, encoding="utf-8")
            elif ext == ".pdf":
                from langchain_community.document_loaders import PyPDFLoader
                loader = PyPDFLoader(source)
            elif ext == ".docx":
                from langchain_community.document_loaders import Docx2txtLoader
                loader = Docx2txtLoader(source)
            elif ext == ".mhtml":
                from langchain_community.document_loaders import MHTMLLoader
                loader = MHTMLLoader(source)
            elif ext == ".html":
                from langchain_community.document_loaders import BSHTMLLoader
                loader = BSHTMLLoader(source)
            else:
                logger.warning(f"Unsupported file extension: {ext}")
                return []
            
            return await to_thread.run_sync(loader.load)

        except Exception as exc:
            logger.error(f"Error loading document from {source}: {exc}")
            return []

    @staticmethod
    def _chunk_documents(documents: List[Document], config: RagEmbeddingConfig) -> List[Document]:
        """Split documents into smaller chunks based on configuration."""
        splitter = RecursiveCharacterTextSplitter(
            chunk_size=config.chunk_size,
            chunk_overlap=config.chunk_overlap,
        )
        return splitter.split_documents(documents)

    @staticmethod
    async def _get_embeddings_model(config: RagEmbeddingConfig):
        """Initialize the appropriate embeddings model."""
        provider = config.provider.lower()
        if provider == "openai":
            from langchain_openai import OpenAIEmbeddings
            return OpenAIEmbeddings(
                api_key=config.api_token,
                base_url=config.api_endpoint,
                model=config.model
            )
        elif provider == "cohere":
            from langchain_cohere import CohereEmbeddings
            return CohereEmbeddings(
                cohere_api_key=config.api_token,
                model=config.model,
                base_url=config.api_endpoint
            )
        elif provider == "ollama":
            try:
                from langchain_ollama import OllamaEmbeddings
                return OllamaEmbeddings(
                    base_url=config.api_endpoint,
                    model=config.model
                )
            except ImportError:
                raise RuntimeError("langchain_ollama not installed")
        else:
            raise ValueError(f"Unsupported embedding provider: {provider}")

    @staticmethod
    def _get_milvus_uri(config: RagVectorStoreConfig) -> str:
        """Get the Milvus connection URI based on configuration."""
        uri = "hiro_rag.db"  # Default local
        if config.data_source == "remote" and config.endpoint:
            uri = config.endpoint
            if "://" not in uri:
                uri = f"http://{uri}"
        return uri

    @staticmethod
    def _get_milvus_client(config: RagVectorStoreConfig) -> Any:
        """Initialize and return a MilvusClient based on configuration."""
        from pymilvus import MilvusClient
        uri = RagService._get_milvus_uri(config)
        return MilvusClient(
            uri=uri,
            token=config.token,
            db_name=config.db_name or ""
        )

    @staticmethod
    async def _store_in_vector_db(chunks: List[Document], db_doc: RagDocument, embed_config: RagEmbeddingConfig, vector_config: RagVectorStoreConfig):
        """Generate embeddings and store in Milvus."""
        embeddings_model = await RagService._get_embeddings_model(embed_config)
        
        from pymilvus import MilvusClient
        
        uri = RagService._get_milvus_uri(vector_config)

        # Connect to Milvus to check/create database (initial connection without db_name to check list_databases)
        client = MilvusClient(uri=uri, token=vector_config.token)
        
        db_name = vector_config.db_name
        if db_name and vector_config.data_source == "remote":
            # For remote Milvus, ensure database exists
            if db_name not in client.list_databases():
                try:
                    client.create_database(db_name)
                    logger.info(f"Created Milvus database: {db_name}")
                except Exception as exc:
                    # Might fail if user doesn't have permissions, but we'll try anyway
                    logger.warning(f"Could not create Milvus database {db_name}: {exc}")
            
            # Switch connection to the specific database
            client.close()
            client = RagService._get_milvus_client(vector_config)
        elif db_name:
            # For Milvus Lite, we can just reconnect with db_name (though it's usually ignored)
            client.close()
            client = RagService._get_milvus_client(vector_config)

        collection_name = vector_config.collection_name or "hiro_documents"
        
        # Ensure collection exists
        if not client.has_collection(collection_name):
            client.create_collection(
                collection_name=collection_name,
                dimension=embed_config.dimensions,
                auto_id=True,
                enable_dynamic_field=True
            )

        from anyio import to_thread
        
        batch_size = embed_config.batch_size or 64
        data = []
        
        # Extract text strings for embedding
        chunk_texts = [chunk.page_content for chunk in chunks]
        
        for i in range(0, len(chunk_texts), batch_size):
            batch_texts = chunk_texts[i : i + batch_size]
            batch_chunks = chunks[i : i + batch_size]
            
            vectors = await to_thread.run_sync(embeddings_model.embed_documents, batch_texts)
            
            for j, vector in enumerate(vectors):
                metadata = batch_chunks[j].metadata or {}
                data.append({
                    "vector": vector,
                    "text": batch_texts[j],
                    "doc_id": db_doc.id,
                    "title": db_doc.title,
                    "tags": db_doc.tags,
                    "metadata": metadata
                })

        if data:
            client.insert(collection_name=collection_name, data=data)
        
        client.close()

    @staticmethod
    async def get_document_chunks(document_id: int) -> List[dict]:
        """Retrieve indexed chunks for a document from Milvus."""
        async with AsyncSessionLocal() as session:
            result = await session.execute(select(RagVectorStoreConfig))
            vector_config = result.scalars().first()
            if not vector_config:
                return []

            client = RagService._get_milvus_client(vector_config)

            collection_name = vector_config.collection_name or "hiro_documents"
            if not client.has_collection(collection_name):
                client.close()
                return []

            results = client.query(
                collection_name=collection_name,
                filter=f"doc_id == {document_id}",
                output_fields=["text", "metadata"],
                limit=100 # Reasonable limit for viewing
            )
            client.close()
            return results

    @staticmethod
    async def search(query: str, limit: int = 5) -> List[dict]:
        """Search for relevant chunks across all documents."""
        async with AsyncSessionLocal() as session:
            # Get configs
            embed_result = await session.execute(select(RagEmbeddingConfig))
            embed_config = embed_result.scalars().first()
            
            vector_result = await session.execute(select(RagVectorStoreConfig))
            vector_config = vector_result.scalars().first()

            if not embed_config or not vector_config:
                return []

            embeddings_model = await RagService._get_embeddings_model(embed_config)
            
            from anyio import to_thread
            query_vector = await to_thread.run_sync(embeddings_model.embed_query, query)

            client = RagService._get_milvus_client(vector_config)

            collection_name = vector_config.collection_name or "hiro_documents"
            if not client.has_collection(collection_name):
                client.close()
                return []

            results = client.search(
                collection_name=collection_name,
                data=[query_vector],
                limit=limit,
                output_fields=["text", "title", "metadata"]
            )
            
            # Flatten results
            hits = []
            if results and len(results) > 0:
                for hit in results[0]:
                    hits.append({
                        "text": hit["entity"]["text"],
                        "title": hit["entity"]["title"],
                        "metadata": hit["entity"]["metadata"],
                        "score": hit["distance"]
                    })
            
            client.close()
            return hits

    @staticmethod
    async def delete_document_data(document_id: int, source_path: str):
        """Purge indexed chunks from Milvus and delete local source file if applicable."""
        # 1. Purge from Milvus
        async with AsyncSessionLocal() as session:
            result = await session.execute(select(RagVectorStoreConfig))
            vector_config = result.scalars().first()
            
            if vector_config:
                try:
                    client = RagService._get_milvus_client(vector_config)

                    collection_name = vector_config.collection_name or "hiro_documents"
                    if client.has_collection(collection_name):
                        client.delete(
                            collection_name=collection_name,
                            filter=f"doc_id == {document_id}"
                        )
                        logger.info(f"Purged chunks for document {document_id} from Milvus")
                    client.close()
                except Exception as exc:
                    logger.error(f"Failed to purge chunks for document {document_id} from Milvus: {exc}")

        # 2. Delete local file if it's in the upload directory
        if source_path and os.path.exists(source_path) and "data/rag_uploads" in source_path:
            try:
                os.remove(source_path)
                logger.info(f"Deleted local source file: {source_path}")
            except Exception as exc:
                logger.error(f"Failed to delete local source file {source_path}: {exc}")
