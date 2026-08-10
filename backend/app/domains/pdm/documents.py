"""The controlled document vault: check-out, upload, check-in.

Two things make this more than a file list.

**Content hashing.** Every revision stores the SHA-256 of its bytes, so "is this
the drawing that was approved?" is a comparison rather than a matter of trust,
and silent corruption in the object store is detectable.

**Check-out locks.** Without one, two engineers can each download revision C,
work for a day, and upload revision D — and whoever saves second silently
destroys the other's work. The lock makes the collision happen at the start,
when it costs a conversation instead of a day.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core import audit
from app.core.audit import AuditAction
from app.core.filestore import content_key, get_file_store
from app.core.principal import Principal
from app.domains.pdm.models import Document, DocumentKind, DocumentRevision, Part
from app.domains.pdm.revisioning import next_revision
from app.domains.pdm.schemas import DocumentOut, DocumentRevisionOut
from app.tools.registry import ToolError

logger = logging.getLogger(__name__)

__all__ = [
    "check_in",
    "check_out",
    "create_document",
    "fetch_content",
    "list_documents",
    "next_revision",
]


async def _load(session: AsyncSession, document_number: str) -> Document:
    document = (
        await session.execute(
            select(Document)
            .where(Document.document_number == document_number.strip().upper())
            .options(selectinload(Document.revisions))
        )
    ).scalar_one_or_none()
    if document is None:
        raise ToolError(f"No document numbered {document_number!r}.")
    return document


async def _to_out(session: AsyncSession, document: Document) -> DocumentOut:
    part_number = None
    if document.related_part_id is not None:
        part_number = (
            await session.execute(
                select(Part.part_number).where(Part.id == document.related_part_id)
            )
        ).scalar_one_or_none()
    return DocumentOut(
        id=document.id,
        document_number=document.document_number,
        title=document.title,
        kind=document.kind,
        related_part_number=part_number,
        locked_by=document.locked_by,
        locked_at=document.locked_at,
        revisions=[
            DocumentRevisionOut.model_validate(rev) for rev in document.revisions
        ],
    )


async def create_document(
    session: AsyncSession,
    *,
    actor: Principal,
    document_number: str,
    title: str,
    kind: DocumentKind,
    related_part_number: str | None = None,
    commit: bool = True,
) -> DocumentOut:
    document_number = document_number.strip().upper()
    existing = (
        await session.execute(
            select(Document.id).where(Document.document_number == document_number)
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise ToolError(f"Document {document_number!r} already exists.")

    related_part_id = None
    if related_part_number:
        related_part_id = (
            await session.execute(
                select(Part.id).where(
                    Part.part_number == related_part_number.strip().upper()
                )
            )
        ).scalar_one_or_none()
        if related_part_id is None:
            raise ToolError(f"No part named {related_part_number!r} to attach this to.")

    document = Document(
        document_number=document_number,
        title=title,
        kind=kind,
        related_part_id=related_part_id,
    )
    session.add(document)
    await session.flush()

    audit.record(
        session,
        actor=actor,
        action=AuditAction.CREATE,
        entity_type="Document",
        entity_id=document.id,
        after={"document_number": document_number, "title": title, "kind": kind.value},
    )
    if commit:
        await session.commit()
    await session.refresh(document, ["revisions"])
    return await _to_out(session, document)


async def check_out(
    session: AsyncSession, *, actor: Principal, document_number: str, commit: bool = True
) -> DocumentOut:
    """Claim the right to produce the next revision."""
    document = await _load(session, document_number)

    if document.locked_by is not None and document.locked_by != actor.user_id:
        raise ToolError(
            f"{document.document_number} is checked out by another user "
            f"(since {document.locked_at:%Y-%m-%d %H:%M} UTC). They must check it "
            "in before it can be edited."
        )

    document.locked_by = actor.user_id
    document.locked_at = datetime.now(timezone.utc)
    audit.record(
        session,
        actor=actor,
        action=AuditAction.UPDATE,
        entity_type="Document",
        entity_id=document.id,
        after={"locked_by": str(actor.user_id)},
        reason="Checked out.",
    )
    if commit:
        await session.commit()
    return await _to_out(session, document)


async def check_in(
    session: AsyncSession,
    *,
    actor: Principal,
    document_number: str,
    filename: str,
    data: bytes,
    content_type: str = "application/octet-stream",
    notes: str | None = None,
    eco_id: uuid.UUID | None = None,
    commit: bool = True,
) -> DocumentOut:
    """Upload new content as the next revision, and release the lock."""
    document = await _load(session, document_number)

    if document.locked_by is not None and document.locked_by != actor.user_id:
        raise ToolError(
            f"{document.document_number} is checked out by another user; you "
            "cannot check in over their lock."
        )
    if not data:
        raise ToolError("Refusing to store an empty file as a revision.")

    digest, key = content_key(data, filename)
    latest = document.revisions[-1] if document.revisions else None

    if latest is not None and latest.content_hash == digest:
        raise ToolError(
            f"The uploaded file is byte-identical to revision {latest.revision}. "
            "Issuing a revision that changes nothing makes the history harder to "
            "read without recording anything."
        )

    store = get_file_store()
    await store.put(key, data, content_type)

    revision = DocumentRevision(
        document_id=document.id,
        revision=next_revision(latest.revision if latest else None),
        filename=filename,
        content_type=content_type,
        size_bytes=len(data),
        content_hash=digest,
        storage_key=key,
        uploaded_by=actor.user_id,
        eco_id=eco_id,
        notes=notes,
    )
    session.add(revision)
    document.locked_by = None
    document.locked_at = None
    await session.flush()

    audit.record(
        session,
        actor=actor,
        action=AuditAction.CREATE,
        entity_type="DocumentRevision",
        entity_id=revision.id,
        after={
            "document_number": document.document_number,
            "revision": revision.revision,
            "content_hash": digest,
            "size_bytes": len(data),
        },
        reason=notes,
    )
    if commit:
        await session.commit()

    await session.refresh(document, ["revisions"])
    logger.info(
        "Checked in %s revision %s (%d bytes).",
        document.document_number,
        revision.revision,
        len(data),
    )
    return await _to_out(session, document)


async def fetch_content(
    session: AsyncSession, *, document_number: str, revision: str | None = None
) -> tuple[DocumentRevision, bytes]:
    """Read one revision's bytes back, verifying them against the stored hash."""
    document = await _load(session, document_number)
    if not document.revisions:
        raise ToolError(f"{document.document_number} has no uploaded content yet.")

    if revision is None:
        chosen = document.revisions[-1]
    else:
        wanted = revision.strip().upper()
        chosen = next(
            (rev for rev in document.revisions if rev.revision == wanted), None
        )
        if chosen is None:
            available = ", ".join(rev.revision for rev in document.revisions)
            raise ToolError(
                f"{document.document_number} has no revision {revision!r}. "
                f"Available: {available}"
            )

    data = await get_file_store().get(chosen.storage_key)
    digest, _ = content_key(data, chosen.filename)
    if digest != chosen.content_hash:
        # The stored bytes are not the approved bytes. Serving them would be
        # worse than failing.
        raise ToolError(
            f"{document.document_number} revision {chosen.revision} failed its "
            "integrity check: the stored content does not match the hash "
            "recorded at check-in."
        )
    return chosen, data


async def list_documents(
    session: AsyncSession, *, part_number: str | None = None
) -> list[DocumentOut]:
    query = select(Document).options(selectinload(Document.revisions))
    if part_number:
        part_id = (
            await session.execute(
                select(Part.id).where(Part.part_number == part_number.strip().upper())
            )
        ).scalar_one_or_none()
        if part_id is None:
            raise ToolError(f"No part named {part_number!r}.")
        query = query.where(Document.related_part_id == part_id)

    rows = (await session.execute(query.order_by(Document.document_number))).scalars().all()
    return [await _to_out(session, row) for row in rows]
