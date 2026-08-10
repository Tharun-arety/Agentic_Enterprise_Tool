"""End-to-end backend verification.

    .venv\\Scripts\\python.exe -m scripts.verify

Assumes `python -m scripts.seed` has already run. Checks, in order:

1. The database is reachable and the pgvector extension is installed.
2. Seeded row counts match what seed.py claims to write.
3. Each of the three tools returns correct data when called directly.
4. The full LangGraph turn runs against the real database, driven by the stub
   model client, and emits the expected SSE frame sequence.

Step 4 deliberately uses the stub client so this harness passes with no API key.
That proves the graph, the tools, and the SSE framing — it does NOT prove the
live model call, which is the one thing only a real key can exercise.
"""

from __future__ import annotations

import asyncio
import sys
from datetime import date
from typing import Any

from pydantic import BaseModel
from sqlalchemy import func, select, text

from app.agents.graph import run_agent
from app.core.db import dispose_engine, get_engine, get_session_factory
from app.core.llm import StubModelClient
from app.domains.ecm.service import list_change_requests
from app.domains.knowledge.models import KnowledgeEmbedding
from app.domains.knowledge.service import search_engineering_knowledge
from app.domains.pdm.baselines import diff_baselines
from app.domains.pdm.models import BomEdge, BomType, Part, PartRevision
from app.domains.pdm.service import (
    get_bom_structure,
    get_compliance_rollup,
    get_where_used,
)
from app.domains.qms.models import LabTestRecord, Unit, UnitComponent
from app.domains.qms.ncr import get_non_conformance
from app.domains.qms.service import (
    get_unit_genealogy,
    query_qms_test_metrics,
    trace_lot,
)
from app.tools.registry import ToolError

PASS = "  PASS"
FAIL = "  FAIL"

failures: list[str] = []


def check(condition: bool, label: str, detail: str = "") -> None:
    if condition:
        print(f"{PASS}  {label}")
    else:
        print(f"{FAIL}  {label}  {detail}")
        failures.append(f"{label} {detail}".strip())


async def step_1_database() -> None:
    print("\n[1] Database connectivity + pgvector")
    engine = get_engine()
    async with engine.connect() as conn:
        version = (await conn.execute(text("SELECT version()"))).scalar_one()
        print(f"       {version.split(',')[0]}")
        installed = (
            await conn.execute(
                text("SELECT count(*) FROM pg_extension WHERE extname = 'vector'")
            )
        ).scalar_one()
        check(installed == 1, "pgvector extension installed")


async def step_2_seed_counts() -> None:
    print("\n[2] Seeded row counts")
    async with get_session_factory()() as session:
        parts = await session.scalar(select(func.count()).select_from(Part))
        revisions = await session.scalar(
            select(func.count()).select_from(PartRevision)
        )
        ebom = await session.scalar(
            select(func.count())
            .select_from(BomEdge)
            .where(BomEdge.bom_type == BomType.EBOM)
        )
        mbom = await session.scalar(
            select(func.count())
            .select_from(BomEdge)
            .where(BomEdge.bom_type == BomType.MBOM)
        )
        tests = await session.scalar(select(func.count()).select_from(LabTestRecord))
        units = await session.scalar(select(func.count()).select_from(Unit))
        components = await session.scalar(
            select(func.count()).select_from(UnitComponent)
        )
        vectors = await session.scalar(
            select(func.count())
            .select_from(KnowledgeEmbedding)
            .where(KnowledgeEmbedding.embedding.isnot(None))
        )
    check(parts == 12, "12 parts", f"(got {parts})")
    check(revisions == 13, "13 part revisions including the released corrective revision", f"(got {revisions})")
    check(ebom == 14, "14 retained EBOM edges across released revisions", f"(got {ebom})")
    check(mbom == 16, "16 retained MBOM edges across released revisions", f"(got {mbom})")
    check(units == 2, "2 built units", f"(got {units})")
    check(components == 10, "10 as-built component lines", f"(got {components})")
    check(tests == 10, "10 lab test records across both units", f"(got {tests})")
    check(vectors == 5, "5 knowledge embeddings with vectors", f"(got {vectors})")


async def step_3_tools() -> None:
    print("\n[3] Tools in isolation")
    async with get_session_factory()() as session:
        # --- PDM: engineering structure -----------------------------------
        bom = await get_bom_structure(session, "ECL-SYS-1000")
        check(bom.root_part_number == "ECL-SYS-1000", "EBOM root is ECL-SYS-1000")
        check(bom.root_revision == "C", "EBOM root resolves to revision C")
        check(bom.total_nodes == 9, "EBOM has 9 nodes", f"(got {bom.total_nodes})")
        check(bom.max_depth == 2, "EBOM is 3 levels deep", f"(got depth {bom.max_depth})")

        def flatten(node: Any) -> dict[str, Any]:
            out: dict[str, Any] = {}

            def walk(current: Any) -> None:
                out[current.part_number] = current
                for child in current.children:
                    walk(child)

            walk(node)
            return out

        nodes = flatten(bom.tree)
        check(
            {"LFS-POR-010", "MAG-ND-051"} <= set(nodes),
            "LaFeSi and released N48H magnet parts present in tree",
        )
        lafesi = nodes["LFS-POR-010"]
        check(lafesi.material_type.value == "LaFeSi", "LFS-POR-010 material is LaFeSi")
        check(
            lafesi.coating_status.value == "Anti-corrosion metal coating",
            "LFS-POR-010 is anti-corrosion coated",
        )
        check(lafesi.quantity == 8, "LFS-POR-010 quantity is 8", f"(got {lafesi.quantity})")

        # --- PDM: effectivity ---------------------------------------------
        before = flatten(
            (
                await get_bom_structure(session, "ECL-SYS-1000", as_of=date(2025, 5, 1))
            ).tree
        )
        check(
            "LFS-POR-009" in before and "LFS-POR-010" not in before,
            "before 2025-06-01 the EBOM contains the epoxy-bonded matrix",
            f"(got {sorted(set(before) & {'LFS-POR-009', 'LFS-POR-010'})})",
        )
        check(
            "LFS-POR-010" in nodes and "LFS-POR-009" not in nodes,
            "after the change the EBOM contains the freeze-cast matrix",
        )

        # --- PDM: manufacturing view ---------------------------------------
        mbom_nodes = flatten(
            (await get_bom_structure(session, "ECL-SYS-1000", bom_type="MBOM")).tree
        )
        check(
            "PKG-CRT-001" in mbom_nodes and "PKG-CRT-001" not in nodes,
            "packaging is on the MBOM and not on the EBOM",
        )
        check(
            "CST-ADH-002" in mbom_nodes and "CST-ADH-002" not in nodes,
            "the assembly adhesive is on the MBOM only",
        )
        check(
            abs(mbom_nodes["FLD-WA-001"].quantity - 1.8) < 1e-9,
            "the fluid is requantified to 1.8 L on the MBOM",
            f"(got {mbom_nodes['FLD-WA-001'].quantity})",
        )
        check(
            mbom_nodes["HYD-PMP-100"].is_phantom,
            "the hydraulic loop is a phantom kit on the MBOM",
        )
        # Located through its parent, not through the flattened map: the seal
        # sits under both the regenerator and the hydraulic loop, and only the
        # regenerator's line carries the scrap allowance.
        amr_seal = next(
            child
            for child in mbom_nodes["ECL-AMR-200"].children
            if child.part_number == "SEA-ORG-004"
        )
        check(
            abs(amr_seal.extended_quantity - 4.2) < 1e-9,
            "5% scrap raises the regenerator O-ring extended quantity to 4.2",
            f"(got {amr_seal.extended_quantity})",
        )

        # --- PDM: where-used ------------------------------------------------
        used = await get_where_used(session, "SEA-ORG-004")
        check(
            {row.part_number for row in used.rows}
            == {"ECL-AMR-200", "HYD-PMP-100", "ECL-SYS-1000"},
            "where-used finds both parents and the product above them",
            f"(got {sorted({r.part_number for r in used.rows})})",
        )
        check(
            used.top_level_products == ["ECL-SYS-1000"],
            "the shared seal reaches exactly one top-level product, named once",
            f"(got {used.top_level_products})",
        )

        # --- PDM: compliance -------------------------------------------------
        rollup = await get_compliance_rollup(session, "ECL-SYS-1000")
        check(
            rollup.heavy_rare_earth_free == "proven",
            "heavy-rare-earth-free is proven across the BOM",
            f"(got {rollup.heavy_rare_earth_free})",
        )
        check(
            rollup.pfas_free == "unproven",
            "PFAS-free is unproven while a component is unassessed",
            f"(got {rollup.pfas_free})",
        )
        check(
            {gap.part_number for gap in rollup.gaps} == {"SEA-ORG-004"},
            "the O-ring is named as the gap",
            f"(got {sorted({g.part_number for g in rollup.gaps})})",
        )
        check(
            rollup.total_direct_gwp is None,
            "no total GWP is reported while a component has no figure",
        )

        # --- PDM: baselines ---------------------------------------------------
        diff = await diff_baselines(
            session,
            "ECLIPSE 1kW — pre freeze-cast (2025-05)",
            "ECLIPSE 1kW — post freeze-cast (2026-01)",
        )
        check(
            [row.part_number for row in diff.added] == ["LFS-POR-010"],
            "the baseline diff shows the freeze-cast matrix added",
            f"(got {[r.part_number for r in diff.added]})",
        )
        check(
            [row.part_number for row in diff.removed] == ["LFS-POR-009"],
            "the baseline diff shows the epoxy-bonded matrix removed",
            f"(got {[r.part_number for r in diff.removed]})",
        )

        # --- QMS: per-unit traceability -------------------------------------
        old_unit = await get_unit_genealogy(session, "ECL-M-097")
        new_unit = await get_unit_genealogy(session, "ECL-M-104")
        old_parts = {line.part_number for line in old_unit.lines}
        new_parts = {line.part_number for line in new_unit.lines}
        check(
            "LFS-POR-009" in old_parts and "LFS-POR-010" not in old_parts,
            "ECL-M-097's build record has the epoxy-bonded matrix it was built with",
            f"(got {sorted(old_parts)})",
        )
        check(
            "LFS-POR-010" in new_parts and "LFS-POR-009" not in new_parts,
            "ECL-M-104's build record has the freeze-cast matrix",
            f"(got {sorted(new_parts)})",
        )
        check(
            "CST-ADH-002" in new_parts,
            "the build record includes the MBOM-only adhesive",
        )
        check(
            "MAG-L-2312" in old_unit.lots and "MAG-L-2508" in new_unit.lots,
            "the two units carry different magnet lots",
            f"(got {old_unit.lots} / {new_unit.lots})",
        )

        trace = await trace_lot(session, "MAG-L-2312")
        check(
            [unit.serial_number for unit in trace.units] == ["ECL-M-097"],
            "the suspect magnet lot traces to exactly one unit",
            f"(got {[u.serial_number for u in trace.units]})",
        )

        # --- QMS: acceptance ------------------------------------------------
        good = await query_qms_test_metrics(session, "ECL-M-104")
        bad = await query_qms_test_metrics(session, "ECL-M-097")
        check(
            good.protocol == "TP-ECL-1K rev A",
            "readings are judged against the protocol",
            f"(got {good.protocol})",
        )
        check(
            (good.pass_count, good.fail_count) == (5, 0),
            "ECL-M-104 passes every reading",
            f"(got {good.pass_count} pass / {good.fail_count} fail)",
        )
        check(
            (bad.pass_count, bad.fail_count) == (3, 2),
            "ECL-M-097 fails its last two readings",
            f"(got {bad.pass_count} pass / {bad.fail_count} fail)",
        )
        failing = [r for r in bad.records if r.result.value == "Fail"]
        check(
            any(
                breach.metric == "temperature_span_delta_K" and breach.lower_limit == 15.0
                for record in failing
                for breach in record.breaches
            ),
            "the failure names the metric and the limit it broke",
        )

        # --- QMS: non-conformance -------------------------------------------
        report = await get_non_conformance(session, "NCR-26-001")
        check(
            report.lot_number == "MAG-L-2312",
            "the seeded NCR is scoped to the material lot, not to one unit",
        )
        check(
            report.affected_units == ["ECL-M-097"],
            "its affected units are derived from the build records",
            f"(got {report.affected_units})",
        )
        check(
            len(report.actions) == 2,
            "it carries a corrective and a preventive action",
            f"(got {len(report.actions)})",
        )
        check(
            report.escalated_ecr_number == "ECR-26-002",
            "the lot NCR is linked to its corrective ECR",
            f"(got {report.escalated_ecr_number})",
        )

        # --- ECM ---------------------------------------------------------
        requests = await list_change_requests(session)
        check(len(requests) == 2, "2 operational change requests seeded", f"(got {len(requests)})")
        ecr = next(item for item in requests if item.number == "ECR-26-001")
        check(
            ecr.affected_part_numbers == ["SEA-ORG-004"],
            "the seeded ECR is raised against the unassessed O-ring",
            f"(got {ecr.affected_part_numbers})",
        )
        check(
            ecr.status.value == "Under review",
            "the seeded ECR is with the board",
            f"(got {ecr.status.value})",
        )
        check(
            ecr.quorum is not None and ecr.quorum.verdict == "incomplete",
            "quorum is incomplete with two of four seats voted",
            f"(got {ecr.quorum.verdict if ecr.quorum else None})",
        )
        check(
            len(ecr.quorum.missing_seats) == 2,
            "two board seats have yet to rule",
            f"(got {ecr.quorum.missing_seats})",
        )
        assessment = ecr.latest_assessment
        check(assessment is not None, "the ECR carries an impact assessment")
        if assessment is not None:
            products = [p.part_number for p in assessment.findings.affected_products]
            check(
                products == ["ECL-SYS-1000"],
                "the assessment reaches the ECLIPSE product",
                f"(got {products})",
            )
            assemblies = {a.part_number for a in assessment.findings.affected_assemblies}
            check(
                {"ECL-AMR-200", "HYD-PMP-100"} <= assemblies,
                "the assessment names both assemblies containing the seal",
                f"(got {sorted(assemblies)})",
            )

        corrective = next(item for item in requests if item.number == "ECR-26-002")
        check(
            corrective.affected_part_numbers == ["MAG-ND-050"],
            "the corrective ECR acts on the failed magnet configuration",
            f"(got {corrective.affected_part_numbers})",
        )
        check(
            corrective.status.value == "Converted",
            "the corrective ECR was converted through a released ECO",
            f"(got {corrective.status.value})",
        )
        check(
            corrective.quorum is not None and corrective.quorum.verdict == "approved",
            "all four CCB seats approved the corrective ECR",
            f"(got {corrective.quorum.verdict if corrective.quorum else None})",
        )

        # Unknown parts must fail loudly, not return an empty tree.
        try:
            await get_bom_structure(session, "NOPE-000")
            check(False, "unknown part raises ToolError")
        except ToolError:
            check(True, "unknown part raises ToolError")

        # --- QMS ---------------------------------------------------------
        qms = await query_qms_test_metrics(session, "ECL-M-104")
        check(qms.sample_count == 5, "5 QMS samples", f"(got {qms.sample_count})")
        times = [record.recorded_at for record in qms.records]
        check(times == sorted(times), "QMS records are in time order")
        span = next(s for s in qms.summaries if s.metric == "temperature_span_delta_K")
        check(
            abs(span.minimum - 15.2) < 1e-9 and abs(span.maximum - 16.1) < 1e-9,
            "temperature span spans 15.2 .. 16.1 K",
            f"(got {span.minimum} .. {span.maximum})",
        )
        hz = next(s for s in qms.summaries if s.metric == "magnetization_cycles_hz")
        check(abs(hz.mean - 2.5) < 1e-9, "drive frequency is 2.5 Hz", f"(got {hz.mean})")
        check(qms.part_number == "ECL-AMR-200", "serial maps to ECL-AMR-200")

        # --- Knowledge ---------------------------------------------------
        knowledge = await search_engineering_knowledge(
            session, "AMR geometry bonding change", limit=5
        )
        check(len(knowledge.hits) == 5, "knowledge search returns all 5 indexed engineering records")
        scores = [hit.similarity for hit in knowledge.hits]
        check(
            scores == sorted(scores, reverse=True),
            "hits are ordered by descending similarity",
            f"(got {scores})",
        )
        if knowledge.semantic:
            check(
                knowledge.hits[0].source_ref == "ECO-24-005",
                "ECO-24-005 ranks first for an AMR-geometry query",
                f"(got {knowledge.hits[0].source_ref})",
            )
        else:
            print(
                "       NOTE: deterministic fallback provider in use — asserting "
                "ordering validity only, not semantic relevance."
            )


async def step_4_graph() -> None:
    print("\n[4] Full graph turn (real DB, stub model client)")
    cases = [
        ("What is the ECLIPSE 1kW chiller made of?", "pdm", "get_bom_structure"),
        ("Show me the test metrics for serial ECL-M-104", "qms", "query_qms_test_metrics"),
        ("Why did the AMR geometry change?", "knowledge", "search_engineering_knowledge"),
    ]

    for message, expected_intent, expected_tool in cases:
        frames: list[tuple[str, dict]] = []

        async def emit(event: str, payload: BaseModel) -> None:
            frames.append((event, payload.model_dump()))

        async with get_session_factory()() as session:
            state = await run_agent(
                session=session,
                emit=emit,
                user_message=message,
                model_client=StubModelClient(),
            )

        events = [event for event, _ in frames]
        check(
            state.get("intent") == expected_intent,
            f"{expected_intent}: routed correctly",
            f"(got {state.get('intent')})",
        )
        check(
            expected_tool in state.get("tool_calls", []),
            f"{expected_intent}: called {expected_tool}",
            f"(got {state.get('tool_calls')})",
        )
        check("agent_state" in events, f"{expected_intent}: emitted agent_state frames")
        check("tool_result" in events, f"{expected_intent}: emitted a tool_result frame")
        check("token" in events, f"{expected_intent}: streamed token frames")
        check(
            bool(state.get("final_text")),
            f"{expected_intent}: produced final text",
        )

        # Frame ordering is the contract the UI depends on: state before data,
        # data before prose.
        first_tool = events.index("tool_result")
        first_token = events.index("token")
        check(
            events.index("agent_state") < first_tool < first_token,
            f"{expected_intent}: frame order is agent_state -> tool_result -> token",
            f"(got {events})",
        )

        payload = next(p for e, p in frames if e == "tool_result")["payload"]
        check("error" not in payload, f"{expected_intent}: tool payload has no error")


async def main() -> int:
    try:
        await step_1_database()
        await step_2_seed_counts()
        await step_3_tools()
        await step_4_graph()
    finally:
        await dispose_engine()

    print()
    if failures:
        print(f"{len(failures)} CHECK(S) FAILED:")
        for failure in failures:
            print(f"  - {failure}")
        return 1
    print("All backend checks passed.")
    print(
        "NOT covered here: the live OpenAI call. This run used the stub model "
        "client, so the graph, tools and SSE framing are proven but the real "
        "model response is not."
    )
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
