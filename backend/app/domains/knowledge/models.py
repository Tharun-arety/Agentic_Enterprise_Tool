"""pgvector-backed store for unstructured engineering knowledge.

ECOs, test-failure write-ups, and spec excerpts do not fit the relational PDM
model, but they are exactly the material an engineer needs when asking "why is
the AMR built this way?". Storing them as embeddings alongside a `related_part_id`
lets the Knowledge agent answer that question and tie the answer back to a part.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    DateTime,
    Enum as SAEnum,
    String,
    Text,
    func,
    Computed,
    ForeignKey,
    Index,
    Integer,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import ARRAY, TSVECTOR, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base
from app.core.embeddings import EMBEDDING_DIMENSIONS
from app.core.enums import enum_values
from app.domains.pdm.models import Part


class DocumentType(str, enum.Enum):
    ECO = "ECO"
    TEST_FAILURE = "Test Failure"
    SPEC = "Spec"
    FIELD_REPORT = "Field Report"


class KnowledgeEmbedding(Base):
    __tablename__ = "knowledge_embeddings"

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    # Width comes from app.core.embeddings so the column and the active
    # provider cannot drift apart. Changing the embedding model to one with a
    # different width means updating EMBEDDING_DIMENSIONS and re-seeding.
    embedding: Mapped[list[float]] = mapped_column(Vector(EMBEDDING_DIMENSIONS))

    related_part_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("parts.id", ondelete="SET NULL"), nullable=True
    )
    document_type: Mapped[DocumentType] = mapped_column(
        SAEnum(
            DocumentType,
            name="document_type",
            native_enum=False,
            length=32,
            values_callable=enum_values,
        )
    )
    text_content: Mapped[str] = mapped_column(Text)
    source_ref: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    related_part: Mapped["Part | None"] = relationship("Part")

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<KnowledgeEmbedding {self.source_ref or self.id}>"


class SourceDocument(Base):
    __tablename__="source_documents"
    id: Mapped[uuid.UUID]=mapped_column(PGUUID(as_uuid=True),primary_key=True,default=uuid.uuid4)
    document_key: Mapped[str]=mapped_column(String(128),unique=True,index=True)
    title: Mapped[str]=mapped_column(String(256))
    document_type: Mapped[str]=mapped_column(String(32),default="controlled")
    acl_labels: Mapped[list[str]]=mapped_column(ARRAY(String(32)),default=lambda:["internal"])
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),server_default=func.now())


class SourceDocumentVersion(Base):
    __tablename__="source_document_versions"
    __table_args__=(UniqueConstraint("source_document_id","version",name="uq_source_document_version"),UniqueConstraint("source_document_id","content_hash",name="uq_source_document_hash"))
    id: Mapped[uuid.UUID]=mapped_column(PGUUID(as_uuid=True),primary_key=True,default=uuid.uuid4)
    source_document_id: Mapped[uuid.UUID]=mapped_column(PGUUID(as_uuid=True),ForeignKey("source_documents.id",ondelete="CASCADE"),index=True)
    version: Mapped[int]=mapped_column(Integer)
    revision: Mapped[str|None]=mapped_column(String(32))
    filename: Mapped[str]=mapped_column(String(256)); content_type: Mapped[str]=mapped_column(String(128)); content_hash: Mapped[str]=mapped_column(String(64),index=True); storage_key: Mapped[str]=mapped_column(String(512))
    extraction_status: Mapped[str]=mapped_column(String(24),default="pending",index=True); extraction_error: Mapped[str|None]=mapped_column(Text); extracted_at: Mapped[datetime|None]=mapped_column(DateTime(timezone=True)); uploaded_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),server_default=func.now()); uploaded_by: Mapped[uuid.UUID|None]=mapped_column(PGUUID(as_uuid=True))


class DocumentChunk(Base):
    __tablename__="document_chunks"
    __table_args__=(Index("ix_document_chunk_search", "search_vector", postgresql_using="gin"),)
    id: Mapped[uuid.UUID]=mapped_column(PGUUID(as_uuid=True),primary_key=True,default=uuid.uuid4)
    document_version_id: Mapped[uuid.UUID]=mapped_column(PGUUID(as_uuid=True),ForeignKey("source_document_versions.id",ondelete="CASCADE"),index=True)
    ordinal: Mapped[int]=mapped_column(Integer)
    text_content: Mapped[str]=mapped_column(Text)
    embedding: Mapped[list[float]]=mapped_column(Vector(EMBEDDING_DIMENSIONS))
    search_vector: Mapped[str]=mapped_column(TSVECTOR,Computed("to_tsvector('english', coalesce(text_content, ''))",persisted=True))
    page: Mapped[int|None]=mapped_column(Integer); sheet: Mapped[str|None]=mapped_column(String(128)); heading: Mapped[str|None]=mapped_column(String(256)); metadata_json: Mapped[dict]=mapped_column(__import__("sqlalchemy.dialects.postgresql",fromlist=["JSONB"]).JSONB,default=dict)
