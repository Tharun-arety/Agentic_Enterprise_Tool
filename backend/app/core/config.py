"""Typed application settings, loaded from the environment / .env file.

No model identifier is hard-coded anywhere else in the codebase. Swapping to a
different (or newer, or cheaper) OpenAI model is a one-line change in .env.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- Database ----------------------------------------------------------
    # Neon connection string. Either the libpq form
    #   postgresql://user:pass@host/db?sslmode=require
    # or the driver-qualified form
    #   postgresql+asyncpg://user:pass@host/db
    # is accepted; db.py normalises whichever you paste in.
    database_url: str = ""

    # --- OpenAI ------------------------------------------------------------
    openai_api_key: str = ""
    # auto = OpenAI when a key exists, otherwise deterministic stub. Set
    # explicitly to "stub" for seeding/evals so a dotenv key cannot spend.
    model_provider: str = "auto"

    # Router + all three retrieval spokes. The retrieval path is intent
    # classification and function calling over structured DB results, so the
    # cheapest tier is the correct tool here, not merely the affordable one.
    # Pinned for reproducible routing/tool trajectories. The provider remains
    # configurable and tests use the deterministic stub without network calls.
    openai_model: str = "gpt-5-nano-2025-08-07"

    # Optional override for the final answer node only. Left empty it falls
    # back to `openai_model`. This exists because the cost asymmetry is
    # lopsided: the router fires on every message and each spoke makes 2+ calls
    # per turn, while synthesis is exactly one call per turn.
    openai_synthesis_model: str = ""
    # Retrieval and evidence synthesis are latency-sensitive, bounded tasks.
    # GPT-5 reasoning tokens count as output tokens, so leaving effort implicit
    # can exhaust a completion budget before any visible text is streamed.
    openai_reasoning_effort: str = "minimal"
    openai_synthesis_max_tokens: int = 1024

    # Cheapest OpenAI embedding model. Changing this to a model with a
    # different width requires a re-seed (see EMBEDDING_DIMENSIONS).
    openai_embedding_model: str = "text-embedding-3-small"

    # --- Identity ----------------------------------------------------------
    # Symmetric signing key for access tokens. The default is a fixed, publicly
    # known development value: a random per-boot secret would silently log
    # everyone out on every reload, which reads as a bug rather than as the
    # security warning it is. `has_production_jwt_secret` drives a loud warning
    # at startup instead.
    jwt_secret: str = "dev-only-insecure-signing-key-change-me"
    jwt_algorithm: str = "HS256"
    jwt_expiry_minutes: int = 15
    refresh_expiry_days: int = 7
    refresh_cookie_name: str = "mt_refresh"
    csrf_cookie_name: str = "mt_csrf"
    # False only for local HTTP development; production Compose sets true.
    cookie_secure: bool = False

    # --- Resilience / integrations ----------------------------------------
    redis_url: str = "redis://localhost:6379/0"
    rate_limit_per_minute: int = 120
    model_timeout_seconds: float = 30.0
    tool_timeout_seconds: float = 15.0
    agent_token_budget: int = 12000
    max_evidence_chars: int = 24000
    backoffice_adapter: str = "local"
    erpnext_base_url: str = "http://erpnext:8080"
    erpnext_api_key: str = ""
    erpnext_api_secret: str = ""
    frappe_webhook_secret: str = ""

    # Password given to every seeded demo user. Seeding is the only consumer;
    # it exists as a setting so the showcase credentials are declared in one
    # place rather than duplicated between the seed script and the README.
    demo_user_password: str = "magnotherm"

    # --- Document vault ----------------------------------------------------
    # Where controlled files live when no object store is configured. Relative
    # to the backend working directory.
    file_vault_path: str = "var/vault"
    # Setting S3_BUCKET switches the vault to object storage; the rest apply
    # only then. S3_ENDPOINT_URL points at MinIO in the compose stack and is
    # left empty for real AWS.
    s3_bucket: str = ""
    s3_endpoint_url: str = ""
    s3_access_key: str = ""
    s3_secret_key: str = ""
    s3_region: str = "us-east-1"

    # --- Tests -------------------------------------------------------------
    # Where `pytest` runs. Left empty — the default — the suite starts its own
    # PostgreSQL from the `pgserver` wheel, which bundles the server binaries
    # and pgvector, so tests need no database, container or daemon and are not
    # paying a network round trip per query.
    #
    # Set it to run against a remote database instead. That is safe: the suite
    # builds and drops its own `mt_test` schema and refuses to start if the
    # tables do not land there.
    test_database_url: str = ""

    # --- Agent behaviour ---------------------------------------------------
    # Hard ceiling on the function-calling loop inside each spoke, so a model
    # that keeps requesting tools cannot spin indefinitely.
    agent_max_tool_iterations: int = 4

    # --- Web ---------------------------------------------------------------
    # Comma-separated CORS allow-list. Both common Next.js dev ports are
    # allowed by default: the browser-side chat fetch is subject to CORS, and a
    # mismatch here surfaces as an opaque network error in the console rather
    # than anything that names the real cause.
    frontend_origin: str = "http://localhost:3001,http://localhost:3000"
    api_host: str = "127.0.0.1"
    api_port: int = 8000

    @property
    def cors_origins(self) -> list[str]:
        return [
            origin.strip()
            for origin in self.frontend_origin.split(",")
            if origin.strip()
        ]

    @property
    def synthesis_model(self) -> str:
        """The model used by the synthesizer node."""
        return self.openai_synthesis_model or self.openai_model

    @property
    def has_openai_key(self) -> bool:
        return bool(self.openai_api_key.strip()) and self.model_provider.lower() != "stub"

    @property
    def has_production_jwt_secret(self) -> bool:
        return not self.jwt_secret.startswith("dev-only-")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
