"""Knowledge-search wire contracts."""

from __future__ import annotations
import uuid

from pydantic import BaseModel

from app.domains.knowledge.models import DocumentType


class KnowledgeHit(BaseModel):
    document_type: DocumentType
    text_content: str
    source_ref: str | None = None
    related_part_number: str | None = None
    # Cosine similarity in [-1, 1]; 1.0 is an exact match. Null when the hit
    # was found by full-text match alone, or when the deterministic fallback
    # provider is in use — there is no similarity to report in either case, and
    # a placeholder derived from the rank would read as a confidence figure it
    # is not.
    similarity: float | None = None
    chunk_id: uuid.UUID | None = None
    source_document_id: uuid.UUID | None = None
    revision: str | None = None
    page: int | None = None
    sheet: str | None = None
    heading: str | None = None
    rrf_score: float | None = None


class KnowledgeResponse(BaseModel):
    query: str
    provider: str
    # False when running on the deterministic fallback provider, so the UI can
    # tell the user their results are not semantically ranked.
    semantic: bool
    hits: list[KnowledgeHit]
