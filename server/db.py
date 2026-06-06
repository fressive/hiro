"""Database setup: async SQLAlchemy engine, Base, and session dependency."""

from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker, declarative_base

from server.core.config import settings


def _async_database_url(url: str) -> str:
    if url.startswith("sqlite:///") and not url.startswith("sqlite+aiosqlite://"):
        return url.replace("sqlite:///", "sqlite+aiosqlite:///")
    return url


DATABASE_URL = _async_database_url(settings.database_url)


def make_async_engine(database_url: str) -> AsyncEngine:
    return create_async_engine(_async_database_url(database_url), future=True)


engine: AsyncEngine = make_async_engine(settings.database_url)

AsyncSessionLocal = sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

Base = declarative_base()


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        yield session
