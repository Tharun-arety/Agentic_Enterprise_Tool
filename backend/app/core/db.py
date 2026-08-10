"""Async SQLAlchemy engine, session factory, and schema bootstrap.

Two Neon-specific details are handled here because both are silent failures
otherwise:

1.  asyncpg does not understand libpq's `?sslmode=require` query parameter. It
    must be stripped from the URL and translated into an `ssl=` connect arg, or
    connecting raises `TypeError: connect() got an unexpected keyword argument
    'sslmode'`. This is the most common failure when pasting a Neon connection
    string straight out of the dashboard.

2.  Neon's *pooled* endpoint (the `-pooler` host) runs PgBouncer in transaction
    mode, which cannot hold the session state asyncpg's prepared statements
    need. Disabling both statement caches makes the pooled endpoint usable.
"""

from __future__ import annotations

import logging
import ssl
from collections.abc import AsyncIterator
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy import text

from app.core.config import get_settings

logger = logging.getLogger(__name__)

# libpq connection parameters that asyncpg does not accept as keyword args.
# They are removed from the URL and, where meaningful, translated below.
_LIBPQ_ONLY_PARAMS = {
    "sslmode",
    "channel_binding",
    "target_session_attrs",
    "options",
    "application_name",
    "connect_timeout",
}

_SSL_REQUIRED_MODES = {"require", "verify-ca", "verify-full", "prefer", "allow"}


class Base(DeclarativeBase):
    """Declarative base shared by app.models and app.vector_models."""


def normalise_database_url(raw_url: str) -> tuple[str, dict[str, Any]]:
    """Return an asyncpg-compatible URL plus the connect_args it needs.

    Accepts any of the forms Neon hands out and returns something
    `create_async_engine` can use directly.
    """
    if not raw_url:
        raise ValueError(
            "DATABASE_URL is not set. Copy backend/.env.example to backend/.env "
            "and paste your Neon connection string."
        )

    parts = urlsplit(raw_url)

    # Force the asyncpg driver regardless of which scheme was pasted in.
    scheme = parts.scheme
    if scheme in ("postgres", "postgresql"):
        scheme = "postgresql+asyncpg"
    elif scheme.startswith("postgresql+") and scheme != "postgresql+asyncpg":
        raise ValueError(
            f"DATABASE_URL requests the {scheme!r} driver, but this backend is "
            "async and requires postgresql+asyncpg."
        )

    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    ssl_mode = query.get("sslmode", "").lower()

    stripped = {k: v for k, v in query.items() if k not in _LIBPQ_ONLY_PARAMS}

    # SQLAlchemy's asyncpg dialect keeps its own prepared-statement cache on top
    # of asyncpg's. It is configured through the URL, not through
    # create_async_engine() kwargs, and must be off for PgBouncer transaction
    # mode (Neon's "-pooler" endpoint).
    stripped.setdefault("prepared_statement_cache_size", "0")

    cleaned_url = urlunsplit(
        (scheme, parts.netloc, parts.path, urlencode(stripped), parts.fragment)
    )

    connect_args: dict[str, Any] = {
        # Required for Neon's pooled (PgBouncer) endpoint; harmless on the
        # direct endpoint.
        "statement_cache_size": 0,
    }

    # Neon always requires TLS. Default to on unless explicitly disabled, so a
    # connection string with no sslmode at all still works.
    if ssl_mode in ("", *_SSL_REQUIRED_MODES):
        connect_args["ssl"] = ssl.create_default_context()
    elif ssl_mode == "disable":
        connect_args["ssl"] = False

    return cleaned_url, connect_args


def _build_engine() -> AsyncEngine:
    settings = get_settings()
    url, connect_args = normalise_database_url(settings.database_url)
    return create_async_engine(
        url,
        connect_args=connect_args,
        pool_pre_ping=True,
        echo=False,
    )


_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def get_engine() -> AsyncEngine:
    """Lazily built so importing this module never opens a connection."""
    global _engine
    if _engine is None:
        _engine = _build_engine()
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    global _session_factory
    if _session_factory is None:
        _session_factory = async_sessionmaker(
            get_engine(), expire_on_commit=False, class_=AsyncSession
        )
    return _session_factory


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency yielding a request-scoped session."""
    async with get_session_factory()() as session:
        yield session


async def dispose_engine() -> None:
    global _engine, _session_factory
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _session_factory = None


async def init_database() -> None:
    """Create the pgvector extension, then all tables.

    The extension must exist before `create_all`, because the ORM metadata
    references the `vector` column type and CREATE TABLE would fail on an
    unknown type.
    """
    # Imported here rather than at module scope so that importing app.core.db
    # does not pull in the whole model layer (and to keep the import graph
    # acyclic: domains import core, never the reverse).
    from app import model_registry  # noqa: F401  (registers every mapper)

    engine = get_engine()
    async with engine.begin() as conn:
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        await conn.run_sync(Base.metadata.create_all)
    logger.info("Database schema ready (pgvector extension present).")


async def create_vector_index() -> None:
    """Build the IVFFlat index over the embedding column.

    Deliberately separate from `init_database` and called *after* seeding:
    IVFFlat builds its cluster centroids from the rows present at creation
    time, so an index built against an empty table gives poor recall.
    """
    engine = get_engine()
    async with engine.begin() as conn:
        row_count = (
            await conn.execute(text("SELECT count(*) FROM knowledge_embeddings"))
        ).scalar_one()
        if row_count == 0:
            logger.warning(
                "Skipping IVFFlat index: knowledge_embeddings is empty, and an "
                "index built now would cluster on nothing. Seed first."
            )
            return

        # `lists` should be roughly sqrt(rows) for large tables; at this corpus
        # size anything above 1 just fragments the search space.
        await conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS knowledge_embeddings_embedding_idx "
                "ON knowledge_embeddings "
                "USING ivfflat (embedding vector_cosine_ops) WITH (lists = 1)"
            )
        )
    logger.info("IVFFlat cosine index ready on knowledge_embeddings.embedding.")
