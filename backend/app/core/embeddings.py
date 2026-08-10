"""Embedding providers behind one interface.

Two implementations:

*   `OpenAIEmbeddingProvider` — the real one, using the cheapest OpenAI
    embedding model.
*   `DeterministicEmbeddingProvider` — a no-API-key fallback so that seeding,
    vector search, the tool layer, and the entire frontend can be built and
    verified before a key exists.

The fallback is NOT semantically meaningful. It produces stable, unit-norm
vectors from a hash of the text, which means cosine distances are arithmetically
valid and repeatable but carry no meaning. Search will return rows in a
consistent yet arbitrary order until a real key is configured. This is stated
loudly rather than hidden, because a silent fallback that looks like it works is
worse than no fallback at all.
"""

from __future__ import annotations

import hashlib
import logging
import math
import random
from abc import ABC, abstractmethod

from app.core.config import get_settings

logger = logging.getLogger(__name__)

# Width of `text-embedding-3-small`. This constant is the single source of
# truth: app.domains.knowledge.models derives its Vector(...) column width from
# it, so the ORM column and the provider can never silently disagree.
EMBEDDING_DIMENSIONS = 1536


class EmbeddingProvider(ABC):
    """Turns text into fixed-width float vectors."""

    dimensions: int = EMBEDDING_DIMENSIONS
    name: str = "abstract"
    is_semantic: bool = False

    @abstractmethod
    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Embed a batch of texts, preserving input order."""

    async def embed_one(self, text: str) -> list[float]:
        return (await self.embed([text]))[0]


class OpenAIEmbeddingProvider(EmbeddingProvider):
    name = "openai"
    is_semantic = True

    def __init__(self) -> None:
        from openai import AsyncOpenAI  # imported lazily to keep startup cheap

        settings = get_settings()
        self._client = AsyncOpenAI(api_key=settings.openai_api_key)
        self._model = settings.openai_embedding_model

    async def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        response = await self._client.embeddings.create(
            model=self._model, input=texts
        )
        # The API documents order preservation, but sorting by index makes that
        # explicit rather than assumed.
        ordered = sorted(response.data, key=lambda item: item.index)
        vectors = [item.embedding for item in ordered]

        actual = len(vectors[0])
        if actual != self.dimensions:
            raise ValueError(
                f"{self._model!r} returns {actual}-dimensional vectors but the "
                f"knowledge_embeddings column is Vector({self.dimensions}). "
                "Update EMBEDDING_DIMENSIONS in app/core/embeddings.py and re-seed."
            )
        return vectors


class DeterministicEmbeddingProvider(EmbeddingProvider):
    """Offline stand-in. Stable across processes and runs, but not semantic."""

    name = "deterministic-fallback"
    is_semantic = False

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._vector_for(text) for text in texts]

    def _vector_for(self, text: str) -> list[float]:
        digest = hashlib.sha256(text.strip().lower().encode("utf-8")).digest()
        seed = int.from_bytes(digest[:8], "big")
        rng = random.Random(seed)
        raw = [rng.gauss(0.0, 1.0) for _ in range(self.dimensions)]
        norm = math.sqrt(sum(value * value for value in raw)) or 1.0
        return [value / norm for value in raw]


_provider: EmbeddingProvider | None = None


def get_embedding_provider() -> EmbeddingProvider:
    """Return the OpenAI provider when a key is configured, else the fallback."""
    global _provider
    if _provider is not None:
        return _provider

    settings = get_settings()
    if settings.has_openai_key:
        _provider = OpenAIEmbeddingProvider()
        logger.info(
            "Embeddings: OpenAI %s (%d dimensions).",
            settings.openai_embedding_model,
            EMBEDDING_DIMENSIONS,
        )
    else:
        _provider = DeterministicEmbeddingProvider()
        logger.warning(
            "Embeddings: OPENAI_API_KEY is not set, using the deterministic "
            "fallback. Vector search WILL return results, but their ordering is "
            "arbitrary rather than semantic. Set OPENAI_API_KEY in backend/.env "
            "and re-run the seed script for real retrieval quality."
        )
    return _provider


def reset_embedding_provider() -> None:
    """Drop the cached provider (used by tests and by the seed script)."""
    global _provider
    _provider = None
