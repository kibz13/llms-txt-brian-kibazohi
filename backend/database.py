import os
from collections.abc import AsyncGenerator
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker
from sqlmodel import SQLModel

load_dotenv(Path(__file__).parent / ".env")

# Railway provides postgresql:// — asyncpg requires postgresql+asyncpg://
_raw_url = os.getenv("DATABASE_URL", "")
DATABASE_URL = _raw_url.replace("postgresql://", "postgresql+asyncpg://", 1) if _raw_url.startswith("postgresql://") else _raw_url

_engine = None
_session_factory = None


def get_engine():
    global _engine, _session_factory
    if _engine is None:
        if not DATABASE_URL:
            raise RuntimeError("DATABASE_URL is not set")
        _engine = create_async_engine(DATABASE_URL, echo=False, future=True)
        _session_factory = sessionmaker(
            _engine, class_=AsyncSession, expire_on_commit=False
        )
    return _engine, _session_factory


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    _, session_factory = get_engine()
    async with session_factory() as session:
        yield session


async def create_tables() -> None:
    """Create all tables. Used in development — production uses Alembic."""
    engine, _ = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
