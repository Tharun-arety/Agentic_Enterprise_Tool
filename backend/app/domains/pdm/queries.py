"""Raw SQL for the parts of PDM that recursion makes awkward in the ORM.

Both traversals share three properties worth stating once:

*   **Cycle safety.** `path` accumulates the ids visited so far. Its `ANY(...)`
    guard stops a malformed (cyclic) structure from recursing forever, and it
    doubles as the key that distinguishes a component appearing under several
    parents.
*   **Effectivity.** Every edge is filtered against an as-of date. Bounds are
    half-open: `effective_to` is the first day the line no longer applies.
*   **Explicit casts on both arms.** PostgreSQL requires the non-recursive and
    recursive terms of a `UNION ALL` to agree on column types exactly, and the
    error when they do not names the column position rather than the column.
"""

from __future__ import annotations

from sqlalchemy import text

# Depth ceiling for traversal. Also a backstop: combined with the cycle guard
# it makes a malformed structure impossible to hang on.
MAX_BOM_DEPTH = 12

# Resolves each part to the revision a BOM edge means when it does not pin one:
# the most recently released revision as at the query date, falling back to the
# newest revision of any state so a part still in design can be exploded during
# development.
#
# The date filter is what makes an engineering change visible in the structure.
# A change order supersedes a revision rather than editing edges in place, so
# without it every historical explode would return today's revisions and the
# as-of date would silently only apply to line-level effectivity.
_EFFECTIVE_REVISION = """
    effective_rev AS (
        SELECT DISTINCT ON (pr.part_id)
            pr.part_id,
            pr.id AS revision_id
        FROM part_revisions pr
        WHERE pr.released_at IS NULL
           OR pr.released_at::date <= CAST(:as_of AS date)
        ORDER BY pr.part_id,
                 (pr.lifecycle_state = 'Released') DESC,
                 pr.released_at DESC NULLS LAST,
                 pr.created_at DESC
    )
"""

# --------------------------------------------------------------------------
# Downward: explode a product into its components
# --------------------------------------------------------------------------

BOM_EXPLODE = text(
    f"""
    WITH RECURSIVE {_EFFECTIVE_REVISION},
    bom AS (
        SELECT
            p.id                          AS part_id,
            rr.id                         AS revision_id,
            p.part_number,
            p.description,
            p.material_type,
            p.coating_status,
            p.part_class,
            p.is_configuration_item,
            p.pfas_free,
            p.contains_heavy_rare_earth,
            p.rohs_reach_status,
            p.gwp_direct,
            p.standard_cost,
            CAST(p.unit_of_measure AS text)     AS unit_of_measure,
            CAST(rr.revision AS text)           AS revision,
            CAST(rr.lifecycle_state AS text)    AS lifecycle_state,
            CAST(1 AS numeric)                  AS quantity,
            CAST(1 AS numeric)                  AS extended_quantity,
            CAST(NULL AS text)                  AS find_number,
            CAST(NULL AS text)                  AS reference_designator,
            CAST(NULL AS integer)               AS operation_seq,
            FALSE                               AS is_phantom,
            CAST(0 AS numeric)                  AS scrap_factor,
            0                                   AS depth,
            ARRAY[p.id::text]                   AS path
        FROM parts p
        JOIN part_revisions rr
          ON rr.id = COALESCE(
                 CAST(:root_revision_id AS uuid),
                 (SELECT er.revision_id FROM effective_rev er WHERE er.part_id = p.id)
             )
        WHERE p.part_number = :part_number

        UNION ALL

        SELECT
            c.id,
            COALESCE(e.child_revision_id, er.revision_id),
            c.part_number,
            c.description,
            c.material_type,
            c.coating_status,
            c.part_class,
            c.is_configuration_item,
            c.pfas_free,
            c.contains_heavy_rare_earth,
            c.rohs_reach_status,
            c.gwp_direct,
            c.standard_cost,
            CAST(e.unit_of_measure AS text),
            CAST(COALESCE(cr.revision, '-') AS text),
            CAST(COALESCE(cr.lifecycle_state, 'In design') AS text),
            e.quantity,
            -- Scrap compounds down the tree: a 2% loss on a sub-assembly means
            -- 2% more of everything inside it, not 2% of the finished item.
            bom.extended_quantity * e.quantity * (1 + e.scrap_factor),
            CAST(e.find_number AS text),
            CAST(e.reference_designator AS text),
            e.operation_seq,
            e.is_phantom,
            e.scrap_factor,
            bom.depth + 1,
            bom.path || c.id::text
        FROM bom
        JOIN bom_edges e
          ON e.parent_revision_id = bom.revision_id
         AND e.bom_type = :bom_type
         AND (e.effective_from IS NULL OR e.effective_from <= CAST(:as_of AS date))
         AND (e.effective_to   IS NULL OR e.effective_to   >  CAST(:as_of AS date))
        JOIN parts c ON c.id = e.child_part_id
        LEFT JOIN effective_rev er ON er.part_id = c.id
        LEFT JOIN part_revisions cr
               ON cr.id = COALESCE(e.child_revision_id, er.revision_id)
        WHERE bom.depth < :max_depth
          AND NOT c.id::text = ANY(bom.path)
    )
    SELECT *
    FROM bom
    ORDER BY depth, find_number NULLS FIRST, part_number
    """
)


# --------------------------------------------------------------------------
# Upward: which assemblies contain this part
# --------------------------------------------------------------------------
# The engine of engineering change impact analysis. "If we alter the LaFeSi
# matrix, what else is affected?" is this query, and every downstream question
# — which products, which test protocols, which open purchase orders — starts
# from its answer.

WHERE_USED = text(
    """
    WITH RECURSIVE target AS (
        SELECT id FROM parts WHERE part_number = :part_number
    ),
    used_in AS (
        SELECT
            pr.part_id                                       AS parent_part_id,
            pr.id                                            AS parent_revision_id,
            e.child_part_id                                  AS via_part_id,
            e.quantity,
            1                                                AS depth,
            ARRAY[e.child_part_id::text, pr.part_id::text]   AS path
        FROM bom_edges e
        JOIN part_revisions pr ON pr.id = e.parent_revision_id
        WHERE e.child_part_id = (SELECT id FROM target)
          AND e.bom_type = :bom_type
          AND (e.effective_to IS NULL OR e.effective_to > CAST(:as_of AS date))

        UNION ALL

        SELECT
            pr.part_id,
            pr.id,
            e.child_part_id,
            e.quantity,
            used_in.depth + 1,
            used_in.path || pr.part_id::text
        FROM used_in
        JOIN bom_edges e
          ON e.child_part_id = used_in.parent_part_id
         AND e.bom_type = :bom_type
         AND (e.effective_to IS NULL OR e.effective_to > CAST(:as_of AS date))
        JOIN part_revisions pr ON pr.id = e.parent_revision_id
        WHERE used_in.depth < :max_depth
          AND NOT pr.part_id::text = ANY(used_in.path)
    )
    SELECT DISTINCT
        p.part_number,
        p.description,
        p.part_class,
        p.is_configuration_item,
        CAST(pr.revision AS text)        AS revision,
        CAST(pr.lifecycle_state AS text) AS lifecycle_state,
        u.quantity,
        u.depth,
        via.part_number                  AS via_part_number,
        -- A part nothing else contains is a top-level product. That is the set
        -- a change notice has to be issued against.
        NOT EXISTS (
            SELECT 1
            FROM bom_edges up
            JOIN part_revisions upr ON upr.id = up.parent_revision_id
            WHERE up.child_part_id = u.parent_part_id
              AND up.bom_type = :bom_type
              AND (up.effective_to IS NULL OR up.effective_to > CAST(:as_of AS date))
        )                                AS is_top_level
    FROM used_in u
    JOIN parts p           ON p.id = u.parent_part_id
    JOIN part_revisions pr ON pr.id = u.parent_revision_id
    JOIN parts via         ON via.id = u.via_part_id
    ORDER BY u.depth, p.part_number
    """
)
