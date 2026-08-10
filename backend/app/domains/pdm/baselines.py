"""Configuration baselines and the diff between them (ISO 10007).

A baseline is a frozen statement of what a product consisted of at one moment:
the configuration a change is measured against, an audit is conducted against,
and a shipped unit is traced back to.

It is stored as a snapshot rather than recomputed on demand. That is the whole
point — a "baseline" that reflects today's data answers a different question
every time it is asked, which makes it useless as the thing later states are
compared to.

The diff is keyed by **path**, not by part number. A component appearing under
two parents is two lines with two quantities, and collapsing them would hide a
change to one of them.
"""

from __future__ import annotations

import logging
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import audit
from app.core.audit import AuditAction
from app.core.principal import Principal
from app.domains.pdm.models import BomType, ConfigurationBaseline, Part
from app.domains.pdm.schemas import (
    BaselineDiff,
    BaselineDiffRow,
    BaselineOut,
    BomNode,
)
from app.domains.pdm.service import get_bom_structure, latest_revision
from app.tools.registry import ToolError

logger = logging.getLogger(__name__)

# The fields a diff reports on. Description is deliberately excluded: rewording
# a description is not a configuration change, and including it would bury the
# lines that matter under editorial noise.
_COMPARED_FIELDS = (
    "revision",
    "quantity",
    "unit_of_measure",
    "find_number",
    "operation_seq",
    "is_phantom",
    "scrap_factor",
    "lifecycle_state",
)


def _flatten(tree: BomNode) -> list[dict]:
    """Depth-first flatten, each line carrying the path that identifies it."""
    lines: list[dict] = []

    def walk(node: BomNode, path: tuple[str, ...]) -> None:
        here = (*path, node.part_number)
        lines.append(
            {
                "path": " / ".join(here),
                "part_number": node.part_number,
                "description": node.description,
                "revision": node.revision,
                "lifecycle_state": node.lifecycle_state.value,
                "quantity": node.quantity,
                "extended_quantity": node.extended_quantity,
                "unit_of_measure": node.unit_of_measure,
                "find_number": node.find_number,
                "operation_seq": node.operation_seq,
                "is_phantom": node.is_phantom,
                "scrap_factor": node.scrap_factor,
                "depth": node.depth,
            }
        )
        for child in node.children:
            walk(child, here)

    walk(tree, ())
    return lines


async def capture_baseline(
    session: AsyncSession,
    *,
    actor: Principal,
    part_number: str,
    name: str,
    platform: str | None = None,
    bom_type: str = BomType.EBOM.value,
    as_of: date | None = None,
    notes: str | None = None,
    eco_id=None,
    commit: bool = True,
) -> BaselineOut:
    """Freeze the current structure of a product under a name."""
    part_number = part_number.strip().upper()
    name = name.strip()

    clash = (
        await session.execute(
            select(ConfigurationBaseline.id).where(ConfigurationBaseline.name == name)
        )
    ).scalar_one_or_none()
    if clash is not None:
        raise ToolError(
            f"A baseline called {name!r} already exists. Baselines are immutable "
            "once captured; choose another name."
        )

    bom = await get_bom_structure(
        session, part_number, bom_type=bom_type, as_of=as_of
    )
    part = (
        await session.execute(select(Part).where(Part.part_number == part_number))
    ).scalar_one()
    revision = await latest_revision(session, part)
    if revision is None:  # pragma: no cover - get_bom_structure would have raised
        raise ToolError(f"{part_number} has no revision to baseline.")

    snapshot = _flatten(bom.tree)
    baseline = ConfigurationBaseline(
        name=name,
        platform=platform,
        root_part_id=part.id,
        root_revision_id=revision.id,
        bom_type=bom.bom_type,
        captured_by=actor.user_id,
        eco_id=eco_id,
        notes=notes,
        snapshot=snapshot,
    )
    session.add(baseline)
    await session.flush()

    audit.record(
        session,
        actor=actor,
        action=AuditAction.CREATE,
        entity_type="ConfigurationBaseline",
        entity_id=baseline.id,
        after={
            "name": name,
            "root": part_number,
            "revision": revision.revision,
            "bom_type": bom.bom_type.value,
            "lines": len(snapshot),
        },
        reason=notes,
    )
    if commit:
        await session.commit()

    logger.info("Captured baseline %r over %d lines.", name, len(snapshot))
    return BaselineOut(
        id=baseline.id,
        name=baseline.name,
        platform=baseline.platform,
        bom_type=baseline.bom_type,
        captured_at=baseline.captured_at,
        eco_id=baseline.eco_id,
        notes=baseline.notes,
        line_count=len(snapshot),
    )


async def list_baselines(session: AsyncSession) -> list[BaselineOut]:
    rows = (
        await session.execute(
            select(ConfigurationBaseline).order_by(
                ConfigurationBaseline.captured_at.desc()
            )
        )
    ).scalars().all()
    return [
        BaselineOut(
            id=row.id,
            name=row.name,
            platform=row.platform,
            bom_type=row.bom_type,
            captured_at=row.captured_at,
            eco_id=row.eco_id,
            notes=row.notes,
            line_count=len(row.snapshot or []),
        )
        for row in rows
    ]


async def _load(session: AsyncSession, name: str) -> ConfigurationBaseline:
    baseline = (
        await session.execute(
            select(ConfigurationBaseline).where(
                func.lower(ConfigurationBaseline.name) == name.strip().lower()
            )
        )
    ).scalar_one_or_none()
    if baseline is None:
        known = (
            await session.execute(
                select(ConfigurationBaseline.name).order_by(ConfigurationBaseline.name)
            )
        ).scalars().all()
        raise ToolError(
            f"No baseline called {name!r}. Known baselines: {', '.join(known)}"
            if known
            else f"No baseline called {name!r}, and none have been captured yet."
        )
    return baseline


def _format(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


async def diff_baselines(
    session: AsyncSession, from_baseline: str, to_baseline: str
) -> BaselineDiff:
    """What changed between two captured configurations."""
    before = await _load(session, from_baseline)
    after = await _load(session, to_baseline)

    if before.bom_type is not after.bom_type:
        raise ToolError(
            f"{before.name!r} is a {before.bom_type.value} and {after.name!r} is a "
            f"{after.bom_type.value}. Comparing an engineering view against a "
            "manufacturing view reports every consumable and packaging line as "
            "an addition, which is not a change."
        )

    before_lines = {line["path"]: line for line in before.snapshot or []}
    after_lines = {line["path"]: line for line in after.snapshot or []}

    added = [
        BaselineDiffRow(
            kind="added",
            path=path,
            part_number=line["part_number"],
            after=f"qty {_format(line.get('quantity'))} rev {line.get('revision')}",
        )
        for path, line in sorted(after_lines.items())
        if path not in before_lines
    ]
    removed = [
        BaselineDiffRow(
            kind="removed",
            path=path,
            part_number=line["part_number"],
            before=f"qty {_format(line.get('quantity'))} rev {line.get('revision')}",
        )
        for path, line in sorted(before_lines.items())
        if path not in after_lines
    ]

    changed: list[BaselineDiffRow] = []
    unchanged = 0
    for path in sorted(before_lines.keys() & after_lines.keys()):
        old, new = before_lines[path], after_lines[path]
        deltas = [
            BaselineDiffRow(
                kind="changed",
                path=path,
                part_number=new["part_number"],
                field=field,
                before=_format(old.get(field)),
                after=_format(new.get(field)),
            )
            for field in _COMPARED_FIELDS
            if _format(old.get(field)) != _format(new.get(field))
        ]
        if deltas:
            changed.extend(deltas)
        else:
            unchanged += 1

    return BaselineDiff(
        from_baseline=before.name,
        to_baseline=after.name,
        added=added,
        removed=removed,
        changed=changed,
        unchanged_count=unchanged,
    )
