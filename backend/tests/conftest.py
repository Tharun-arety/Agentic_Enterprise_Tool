"""Test harness.

The suite runs against a real Postgres because the schema depends on things no
in-memory database provides: `pgvector`'s `vector` type, `ARRAY`, and `JSONB`.
Swapping in SQLite would mean testing a different schema than the one that
ships, which is worse than not testing it.

Isolation comes from a dedicated schema rather than a dedicated database. Each
session creates `mt_test`, points `search_path` at it, builds every table there,
and drops the whole schema afterwards. Pointing `TEST_DATABASE_URL` at the same
Neon instance as the application is therefore safe: the application's tables
live in `public` and are never opened.

Two details about *how* the redirection is done, both learned the hard way:

*   It uses `search_path`, not SQLAlchemy's `schema_translate_map`. The map only
    rewrites SQLAlchemy-constructed clauses, so ORM queries would land in
    `mt_test` while the hand-written recursive CTEs in `domains/pdm/queries.py`
    kept reading `public` — the suite would appear isolated and quietly
    exercise application data.
*   The path is set with a `SET` statement on every pool **checkout**, not
    through asyncpg's `server_settings`. Neon's proxy accepts only a fixed set
    of startup parameters and drops `search_path` without complaint, on the
    direct endpoint as well as the pooled one.
*   It connects to Neon's **direct** endpoint, deriving it from whatever URL is
    configured, because the setting has to survive between transactions and
    PgBouncer's transaction mode reassigns server connections underneath.

`_assert_isolated` checks the outcome rather than trusting either of these.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import get_settings
from app.core.db import Base, normalise_database_url
from app.core.principal import ActorType, Principal
from app.core.security import hash_password
from app.domains.identity.models import Role, User
from app.tools import loader  # noqa: F401  (populates TOOL_REGISTRY on import)

TEST_SCHEMA = "mt_test"


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line("markers", "db: requires a reachable Postgres.")


@pytest.fixture(scope="session")
def database_url():
    """Where the suite runs.

    Defaults to a PostgreSQL started here in-process, from the `pgserver`
    wheel — which bundles the server binaries *and* pgvector, so `pytest` needs
    no database, no container and no daemon.

    The reason is latency, not convenience. The tests compute almost nothing;
    they are a few thousand small queries, and against a hosted database each
    one costs a network round trip. The same suite that takes a quarter of an
    hour over the wire takes seconds over a loopback socket.

    Set `TEST_DATABASE_URL` to run against a remote database instead — the
    isolation below is built to work either way.
    """
    configured = get_settings().test_database_url
    if configured:
        yield configured
        return

    try:
        import pgserver
    except ImportError:  # pragma: no cover - depends on the install
        pytest.skip(
            "Neither TEST_DATABASE_URL nor the `pgserver` package is available, "
            "so there is nowhere to run the suite."
        )

    # Kept between runs: the directory holds an initialised cluster, which
    # turns a ~13s initdb into a ~0.02s start. It is gitignored.
    pgdata = Path(__file__).resolve().parent.parent / "var" / "testdb"
    pgdata.parent.mkdir(parents=True, exist_ok=True)
    server = pgserver.get_server(pgdata, cleanup_mode="stop")
    # No TLS on a loopback server; without this the URL normalisation would
    # default to requiring it and the connection would fail.
    yield server.get_uri() + "?sslmode=disable"


def direct_endpoint(url: str) -> str:
    """Neon's direct host for a URL that may name the pooled one.

    Session-level `search_path` is the isolation mechanism, and PgBouncer in
    transaction mode does not carry it. Rather than making every developer
    remember to configure a second URL, the pooled suffix is simply dropped.
    A no-op for any host that is not Neon's pooler.
    """
    return url.replace("-pooler.", ".", 1)


@pytest_asyncio.fixture(scope="session")
async def engine(database_url: str):
    url, base_connect_args = normalise_database_url(direct_endpoint(database_url))

    # The schema has to exist before any connection pins `search_path` to it,
    # so it is created on a throwaway engine that still points at `public`.
    bootstrap = create_async_engine(url, connect_args=base_connect_args)
    async with bootstrap.begin() as conn:
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        await conn.execute(text(f"DROP SCHEMA IF EXISTS {TEST_SCHEMA} CASCADE"))
        await conn.execute(text(f"CREATE SCHEMA {TEST_SCHEMA}"))
    await bootstrap.dispose()

    # No `pool_pre_ping`: it adds a round trip to every checkout, and the
    # checkout hook below already exercises the connection. Against a remote
    # database that doubling is the difference between a slow suite and an
    # unusable one.
    engine = create_async_engine(url, connect_args=base_connect_args)

    # On checkout rather than on connect: a pooled connection that has already
    # been handed out once does not fire `connect` again, and the setting does
    # not reliably survive the pool's return-to-pool reset. `public` stays on
    # the path so the `vector` type and `gen_random_uuid()` still resolve;
    # `mt_test` is first, so unqualified reads and writes land there.
    @event.listens_for(engine.sync_engine, "checkout")
    def _set_search_path(dbapi_connection, _record, _proxy):  # type: ignore[no-untyped-def]
        cursor = dbapi_connection.cursor()
        cursor.execute(f"SET search_path TO {TEST_SCHEMA}, public")
        cursor.close()

    # Import side effect: registers every mapper before create_all.
    from app import model_registry  # noqa: F401

    # `checkfirst=False` on purpose. The default asks the database whether each
    # table exists, and that question is answered through `search_path` — which
    # still contains `public`, where the application's tables of the same names
    # live. Every CREATE would be skipped and the test schema left empty. The
    # schema was dropped and recreated moments ago, so there is nothing here to
    # collide with.
    async with engine.begin() as conn:
        await conn.run_sync(lambda sync_conn: Base.metadata.create_all(sync_conn, checkfirst=False))

    await _assert_isolated(engine)
    yield engine

    await engine.dispose()
    teardown = create_async_engine(url, connect_args=base_connect_args)
    async with teardown.begin() as conn:
        await conn.execute(text(f"DROP SCHEMA IF EXISTS {TEST_SCHEMA} CASCADE"))
    await teardown.dispose()


async def _assert_isolated(engine) -> None:
    """Refuse to run unless the tables really landed in the test schema.

    Both isolation mechanisms tried here fail *silently* when they fail — the
    suite goes green while reading and truncating application data. So the
    outcome is checked, not assumed.
    """
    async with engine.connect() as conn:
        landed = (
            await conn.execute(
                text(
                    "SELECT count(*) FROM information_schema.tables "
                    "WHERE table_schema = :schema"
                ),
                {"schema": TEST_SCHEMA},
            )
        ).scalar_one()
        # Where an unqualified name actually resolves, which is the thing that
        # matters for the raw-SQL queries the ORM never sees.
        resolved = (
            await conn.execute(text("SELECT current_schema()"))
        ).scalar_one()

    expected = len(Base.metadata.tables)
    if landed != expected or resolved != TEST_SCHEMA:
        raise RuntimeError(
            f"Test isolation failed: expected {expected} tables in schema "
            f"{TEST_SCHEMA!r} and unqualified names to resolve there, but found "
            f"{landed} tables and current_schema()={resolved!r}. Refusing to run "
            "against what is probably the application schema."
        )


@pytest_asyncio.fixture
async def session(engine) -> AsyncIterator[AsyncSession]:
    """A session whose rows are removed after the test.

    The services under test commit, so a wrapping transaction cannot be rolled
    back to undo them. Truncating between tests is the honest alternative: it
    exercises the same commit path production does.
    """
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with factory() as session:
        yield session

    # Qualified explicitly rather than relying on `search_path`: this is the
    # statement that would do the most damage if the redirection ever lapsed.
    tables = ", ".join(f'{TEST_SCHEMA}."{name}"' for name in Base.metadata.tables)
    async with engine.begin() as conn:
        await conn.execute(text(f"TRUNCATE TABLE {tables} RESTART IDENTITY CASCADE"))


# Hashed once for the whole session. Argon2 is deliberately expensive, and the
# ECM fixtures alone create five users per test — re-deriving the same hash from
# the same password each time costs minutes across the suite and proves nothing
# that `test_security.py` does not already prove directly.
TEST_PASSWORD = "correct-horse"
_TEST_PASSWORD_HASH = hash_password(TEST_PASSWORD)


@pytest_asyncio.fixture
async def user_factory(session: AsyncSession):
    """Create a persisted user with the given roles."""

    async def make(*roles: Role, email: str | None = None, active: bool = True) -> User:
        user = User(
            email=email or f"{uuid.uuid4().hex[:12]}@magnotherm.test",
            full_name="Test User",
            password_hash=_TEST_PASSWORD_HASH,
            roles=[role.value for role in roles],
            is_active=active,
        )
        session.add(user)
        await session.commit()
        return user

    return make


def principal_for(user: User) -> Principal:
    return Principal(
        actor_type=ActorType.HUMAN,
        user_id=user.id,
        email=user.email,
        roles=tuple(user.roles),
    )
