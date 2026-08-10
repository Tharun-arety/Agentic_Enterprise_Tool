"""Traceability, in both directions.

Forward: given a serial number, what went into it — through serialised
sub-assemblies as well as loose components. Backward: given a lot of material,
which finished units contain it.

The backward direction is the one that matters under pressure. When a supplier
reports a bad batch, or a field failure is traced to a material, the question is
"which units are affected?" and the acceptable answers are a list or nothing.
"Every unit we ever built" is what a system without lot-level genealogy is
forced to say.
"""

from __future__ import annotations

from sqlalchemy import text

MAX_GENEALOGY_DEPTH = 8

# Walks down from a unit through its build record. A component that is itself a
# serialised article continues into that unit's own genealogy, so a product
# built from serialised sub-assemblies reads as one tree.
#
# `path` guards against a build record that somehow references itself, which is
# not supposed to be possible but would otherwise recurse until the depth limit.
UNIT_GENEALOGY = text(
    """
    WITH RECURSIVE genealogy AS (
        SELECT
            uc.id                                   AS component_id,
            u.serial_number                         AS parent_serial,
            p.part_number,
            p.description,
            CAST(pr.revision AS text)               AS revision,
            uc.quantity,
            CAST(uc.unit_of_measure AS text)        AS unit_of_measure,
            CAST(uc.lot_number AS text)             AS lot_number,
            CAST(uc.supplier_lot AS text)           AS supplier_lot,
            CAST(uc.child_serial_number AS text)    AS child_serial_number,
            CAST(uc.position AS text)               AS position,
            uc.operation_seq,
            uc.installed_at,
            0                                       AS depth,
            -- Cast to text: `serial_number` is varchar(64), and concatenating
            -- in the recursive term widens it to varchar, which PostgreSQL
            -- rejects as a type mismatch between the two arms.
            ARRAY[u.serial_number::text]            AS path
        FROM units u
        JOIN unit_components uc ON uc.unit_id = u.id
        JOIN parts p            ON p.id = uc.part_id
        LEFT JOIN part_revisions pr ON pr.id = uc.part_revision_id
        WHERE u.serial_number = :serial_number

        UNION ALL

        SELECT
            uc.id,
            child.serial_number,
            p.part_number,
            p.description,
            CAST(pr.revision AS text),
            uc.quantity,
            CAST(uc.unit_of_measure AS text),
            CAST(uc.lot_number AS text),
            CAST(uc.supplier_lot AS text),
            CAST(uc.child_serial_number AS text),
            CAST(uc.position AS text),
            uc.operation_seq,
            uc.installed_at,
            genealogy.depth + 1,
            genealogy.path || child.serial_number::text
        FROM genealogy
        JOIN units child        ON child.serial_number = genealogy.child_serial_number
        JOIN unit_components uc ON uc.unit_id = child.id
        JOIN parts p            ON p.id = uc.part_id
        LEFT JOIN part_revisions pr ON pr.id = uc.part_revision_id
        WHERE genealogy.depth < :max_depth
          AND NOT child.serial_number = ANY(genealogy.path)
    )
    SELECT *
    FROM genealogy
    ORDER BY depth, position NULLS LAST, part_number
    """
)


# Given a lot, every unit containing it — directly, or through a serialised
# sub-assembly that contains it.
LOT_TRACE = text(
    """
    WITH RECURSIVE affected AS (
        SELECT
            u.id            AS unit_id,
            u.serial_number,
            0               AS depth,
            ARRAY[u.id]     AS path
        FROM unit_components uc
        JOIN units u ON u.id = uc.unit_id
        WHERE uc.lot_number = :lot_number
           OR uc.supplier_lot = :lot_number

        UNION ALL

        -- Step outward: a unit containing an affected unit is itself affected.
        SELECT
            parent.id,
            parent.serial_number,
            affected.depth + 1,
            affected.path || parent.id
        FROM affected
        JOIN units child        ON child.id = affected.unit_id
        JOIN unit_components uc ON uc.child_serial_number = child.serial_number
        JOIN units parent       ON parent.id = uc.unit_id
        WHERE affected.depth < :max_depth
          AND NOT parent.id = ANY(affected.path)
    )
    SELECT DISTINCT
        a.serial_number,
        CAST(u.status AS text)  AS status,
        p.part_number,
        u.built_at,
        u.customer_ref,
        a.depth
    FROM affected a
    JOIN units u ON u.id = a.unit_id
    JOIN parts p ON p.id = u.part_id
    ORDER BY a.depth, a.serial_number
    """
)


# Units whose build record contains a given part, at any level. This is what
# turns "we are changing this component" into "these specific articles carry
# test evidence that is about to stop being valid".
UNITS_CONTAINING_PART = text(
    """
    WITH RECURSIVE affected AS (
        SELECT
            u.id            AS unit_id,
            0               AS depth,
            ARRAY[u.id]     AS path
        FROM unit_components uc
        JOIN units u ON u.id = uc.unit_id
        JOIN parts p ON p.id = uc.part_id
        WHERE p.part_number = ANY(:part_numbers)

        UNION ALL

        SELECT
            parent.id,
            affected.depth + 1,
            affected.path || parent.id
        FROM affected
        JOIN units child        ON child.id = affected.unit_id
        JOIN unit_components uc ON uc.child_serial_number = child.serial_number
        JOIN units parent       ON parent.id = uc.unit_id
        WHERE affected.depth < :max_depth
          AND NOT parent.id = ANY(affected.path)
    )
    SELECT DISTINCT u.serial_number, p.part_number
    FROM affected a
    JOIN units u ON u.id = a.unit_id
    JOIN parts p ON p.id = u.part_id

    UNION

    -- A unit built *as* the part itself, not merely containing it.
    SELECT u.serial_number, p.part_number
    FROM units u
    JOIN parts p ON p.id = u.part_id
    WHERE p.part_number = ANY(:part_numbers)
    """
)
