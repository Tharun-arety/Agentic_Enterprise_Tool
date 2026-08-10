"""Alembic environment.

The URL is taken from the application settings and put through the same
`normalise_database_url` the app uses, so a Neon connection string that works
for `uvicorn` also works for `alembic upgrade head`. Hard-coding it in
alembic.ini would give two places for it to be wrong in different ways.

Only the online (real connection) path is implemented. Offline `--sql` mode
would emit DDL for the `vector` column type without being able to check the
extension exists, which produces a script that fails halfway on first run.
"""

from __future__ import annotations

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool, text
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from app.core.config import get_settings
from app.core.db import Base, normalise_database_url

# Import side effect: every mapper must be registered before autogenerate
# compares metadata against the database, or it will script a DROP TABLE for
# every table whose module was not imported.
from app import model_registry  # noqa: F401,E402

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

_url, _connect_args = normalise_database_url(get_settings().database_url)
config.set_main_option("sqlalchemy.url", _url)

# Deliberately absent: a "run the migrations against a throwaway schema"
# switch. `schema_translate_map` only rewrites SQLAlchemy-constructed table
# clauses, so `op.create_table` would honour it while `op.add_column`,
# `op.alter_column` and raw `op.execute` would not — a migration that mixes
# them would write half to the scratch schema and half to the real one, and
# only say so if it happened to fail. Migrations are verified by running them
# against the development database, whose data is synthetic and re-seedable.


# Indexes that exist in the database on purpose but are absent from the ORM
# metadata. Without this, every autogenerate run scripts a DROP for them.
_UNMANAGED_INDEXES = {
    # Built by app.core.db.create_vector_index *after* seeding, because IVFFlat
    # derives its cluster centroids from the rows present when it is created —
    # an index built against an empty table gives poor recall. A migration
    # cannot express "after the data exists", so it stays out of Alembic's
    # hands.
    "knowledge_embeddings_embedding_idx",
}


def _include_object(obj, name, type_, reflected, compare_to) -> bool:  # type: ignore[no-untyped-def]
    if type_ == "index" and name in _UNMANAGED_INDEXES:
        return False
    # Alembic's own bookkeeping table, which is not part of the application
    # schema and must never appear in a diff against it.
    if type_ == "table" and name == "alembic_version":
        return False
    return True


def _run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        include_object=_include_object,
        # Without this, a column type change is silently skipped and the
        # migration appears to succeed while the schema keeps drifting.
        compare_type=True,
        compare_server_default=True,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
        connect_args=_connect_args,
    )

    async with connectable.connect() as connection:
        # The `vector` type must exist before any migration references it.
        # Committed on its own: CREATE EXTENSION inside the migration's
        # transaction would be rolled back with it on failure, leaving a
        # half-applied schema that cannot be re-run.
        await connection.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        await connection.commit()
        await connection.run_sync(_run_migrations)

    await connectable.dispose()


if context.is_offline_mode():
    raise SystemExit(
        "Offline (--sql) mode is not supported: the schema depends on the "
        "pgvector extension, which cannot be verified without a connection."
    )

asyncio.run(run_async_migrations())
