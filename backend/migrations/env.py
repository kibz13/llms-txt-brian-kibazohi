import asyncio
import os
from logging.config import fileConfig
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import pool
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel import SQLModel

from alembic import context

# Import all models so SQLModel.metadata is populated
import models  # noqa: F401

load_dotenv(Path(__file__).parent.parent / ".env")

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = SQLModel.metadata

# Read DATABASE_URL from env (overrides alembic.ini value)
# Railway provides postgresql:// — asyncpg requires postgresql+asyncpg://
_raw = os.getenv("DATABASE_URL", config.get_main_option("sqlalchemy.url", ""))
DATABASE_URL = _raw.replace("postgresql://", "postgresql+asyncpg://", 1) if _raw.startswith("postgresql://") else _raw


def run_migrations_offline() -> None:
    context.configure(
        url=DATABASE_URL,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    engine = create_async_engine(DATABASE_URL, poolclass=pool.NullPool)
    async with engine.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
