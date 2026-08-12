"""Retrieval over the engineering corpus.

Two stores hold evidence, for historical reasons that are worth keeping: the
chunked ingestion pipeline (`document_chunks`, with access labels, revisions
and page anchors) and the flat seeded corpus (`knowledge_embeddings`, which
carries the curated change orders and failure reports and links them to parts).

Both are searched and **fused into one ranking**. They used to be concatenated
instead — chunk hits first, then the flat store used only to top up whatever
space was left — which meant a perfect match in the flat store could never
outrank a poor chunk match. That is how an AMR-geometry query returned the
magnet change notice ahead of the freeze-cast matrix release that was actually
about AMR geometry.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.embeddings import get_embedding_provider
from app.domains.knowledge.models import (
    DocumentChunk,
    DocumentType,
    KnowledgeEmbedding,
    SourceDocument,
    SourceDocumentVersion,
)
from app.domains.knowledge.schemas import KnowledgeHit, KnowledgeResponse
from app.domains.pdm.models import Part
from app.tools.registry import ToolError

#: What a top full-text hit is worth, expressed on the cosine-similarity scale.
#: A keyword match is a different kind of evidence from vector proximity — it
#: is how an exact part number or change number finds its document — so it has
#: to be able to promote a passage the embedding merely thought was adjacent.
#: 0.25 is roughly the gap between a good and an indifferent cosine score on
#: this corpus, and the bonus decays down the lexical ranking.
LEXICAL_WEIGHT = 0.25

#: Where a lexical-only hit starts from, having no similarity of its own. Low
#: enough that a genuinely semantic match outranks it, high enough that an
#: exact identifier match is not buried.
LEXICAL_FLOOR = 0.2


@dataclass
class _Candidate:
    """One retrievable passage, however it was found."""

    key: str
    #: True cosine similarity where an arm computed one, else None. Reported to
    #: the caller as-is: a rank is not a similarity and must not be dressed up
    #: as one.
    similarity: float | None = None
    lexical_bonus: float = 0.0
    build: Any = None

    @property
    def score(self) -> float:
        """Rank on one scale.

        Reciprocal rank fusion used to do this job, and it was the wrong tool:
        RRF accumulates score when the *same* document appears in several
        lists, but the chunk store and the curated store are disjoint, so
        nothing ever appeared in both. Every candidate scored exactly 1/(k+1)
        for its own arm, every comparison was a tie, and the winner was
        whichever store happened to be inserted first. Both arms come from one
        embedding model, so their cosine scores are directly comparable — which
        makes the fusion a plain sum rather than a rank heuristic.
        """
        return (self.similarity if self.similarity is not None else LEXICAL_FLOOR) + self.lexical_bonus


async def search_engineering_knowledge(
    session: AsyncSession,
    query: str,
    limit: int = 5,
    acl_labels: list[str] | None = None,
    document_type: str | None = None,
) -> KnowledgeResponse:
    query = query.strip()
    if not query:
        raise ToolError("Search query is empty.")

    provider = get_embedding_provider()
    vector = await provider.embed_one(query)
    acl = acl_labels or ["internal"]
    pool = max(limit * 8, 20)

    base = (
        select(DocumentChunk, SourceDocumentVersion, SourceDocument)
        .join(SourceDocumentVersion, SourceDocumentVersion.id == DocumentChunk.document_version_id)
        .join(SourceDocument, SourceDocument.id == SourceDocumentVersion.source_document_id)
        .where(SourceDocument.acl_labels.overlap(acl))
    )
    if document_type:
        base = base.where(SourceDocument.document_type == document_type)

    candidates: dict[str, _Candidate] = {}

    # --- Arm 1: chunk vectors ------------------------------------------------
    # The deterministic fallback provider is not semantic. Letting its arbitrary
    # vectors order the results would be worse than lexical retrieval alone.
    if provider.is_semantic:
        rows = (
            await session.execute(
                base.add_columns(
                    DocumentChunk.embedding.cosine_distance(vector).label("distance")
                )
                .order_by("distance")
                .limit(pool)
            )
        ).all()
        for chunk, version, document, distance in rows:
            key = f"chunk:{chunk.id}"
            candidate = candidates.setdefault(key, _Candidate(key=key))
            candidate.similarity = round(1 - float(distance), 4)
            candidate.build = ("chunk", chunk, version, document)

    # --- Arm 2: chunk full text ---------------------------------------------
    # In web-search syntax a hyphen can mean NOT. Engineering identifiers use
    # hyphens heavily, so match them literally as well as running the normal
    # full-text query (ECN-26-001, MAG-L-2312, and so on).
    ts = func.websearch_to_tsquery("english", query)
    identifiers = set(re.findall(r"\b[A-Z]{2,}(?:-[A-Z0-9]+)+\b", query.upper()))
    conditions = [DocumentChunk.search_vector.op("@@")(ts)]
    for identifier in identifiers:
        conditions.extend(
            (
                SourceDocument.document_key.ilike(f"%{identifier}%"),
                DocumentChunk.text_content.ilike(f"%{identifier}%"),
            )
        )
    rows = (
        await session.execute(
            base.add_columns(func.ts_rank_cd(DocumentChunk.search_vector, ts).label("rank"))
            .where(or_(*conditions))
            .order_by(func.ts_rank_cd(DocumentChunk.search_vector, ts).desc())
            .limit(pool)
        )
    ).all()
    for rank, (chunk, version, document, _rank) in enumerate(rows):
        key = f"chunk:{chunk.id}"
        candidate = candidates.setdefault(key, _Candidate(key=key))
        candidate.build = candidate.build or ("chunk", chunk, version, document)
        candidate.lexical_bonus = max(candidate.lexical_bonus, LEXICAL_WEIGHT / (1 + rank))

    # --- Arm 3: the curated corpus -------------------------------------------
    # A peer arm, not a filler. These rows carry the change orders and failure
    # reports that link directly to parts.
    if provider.is_semantic:
        distance = KnowledgeEmbedding.embedding.cosine_distance(vector)
        rows = (
            await session.execute(
                select(KnowledgeEmbedding, distance.label("distance"), Part.part_number)
                .outerjoin(Part, Part.id == KnowledgeEmbedding.related_part_id)
                .order_by(distance)
                .limit(pool)
            )
        ).all()
        for record, record_distance, part_number in rows:
            key = f"curated:{record.id}"
            candidate = candidates.setdefault(key, _Candidate(key=key))
            candidate.similarity = round(1 - float(record_distance), 4)
            candidate.build = ("curated", record, part_number)

    ordered = sorted(candidates.values(), key=lambda entry: entry.score, reverse=True)[:limit]

    hits: list[KnowledgeHit] = []
    for candidate in ordered:
        if candidate.build is None:
            continue
        kind = candidate.build[0]
        if kind == "chunk":
            _, chunk, version, document = candidate.build
            hits.append(
                KnowledgeHit(
                    document_type=DocumentType.SPEC,
                    text_content=chunk.text_content,
                    source_ref=document.document_key,
                    similarity=candidate.similarity,
                    chunk_id=chunk.id,
                    source_document_id=document.id,
                    revision=version.revision or str(version.version),
                    page=chunk.page,
                    sheet=chunk.sheet,
                    heading=chunk.heading,
                    rrf_score=round(candidate.score, 6),
                )
            )
        else:
            _, record, part_number = candidate.build
            hits.append(
                KnowledgeHit(
                    document_type=record.document_type,
                    text_content=record.text_content,
                    source_ref=record.source_ref,
                    related_part_number=part_number,
                    similarity=candidate.similarity,
                    rrf_score=round(candidate.score, 6),
                )
            )

    return KnowledgeResponse(
        query=query,
        provider=provider.name,
        semantic=provider.is_semantic,
        hits=hits,
    )
