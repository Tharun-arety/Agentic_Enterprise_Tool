"""Inject the Magnotherm replica dataset.

    .venv\\Scripts\\python.exe -m scripts.seed

Idempotent: truncates the tables it owns, then rebuilds them, so re-running
never duplicates rows.

All timestamps are hard-coded constants rather than `datetime.now()`. Seeded
data is therefore byte-identical on every run, which means the QMS chart renders
the same shape every time and any visual diff is a real regression rather than
the clock moving.

Three details in here exist to make the harder machinery demonstrable rather
than merely present:

*   **A superseded component with dated effectivity.** LFS-POR-009 (epoxy
    bonded) phases out on 2025-06-01 and LFS-POR-010 (freeze-cast) phases in
    the same day, which is ECO-24-005 in the knowledge corpus. Exploding the
    ECLIPSE at a date either side of that returns a different structure, and
    the two captured baselines differ because of it.
*   **A component used in two places.** The O-ring appears under both the
    regenerator and the hydraulic loop, so where-used has something real to
    find and the edge table earns its shape.
*   **One unassessed component.** The O-ring has no PFAS declaration, so the
    compliance rollup for the ECLIPSE comes back *unproven* rather than
    proven — the answer an evidence-based claim actually has to give.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import func, select, text
from sqlalchemy.orm import selectinload

from app.core.config import get_settings
from app.core.db import (
    create_vector_index,
    dispose_engine,
    get_session_factory,
    init_database,
)
from app.core.embeddings import get_embedding_provider
from app.core.principal import SYSTEM_PRINCIPAL, ActorType, Principal
from app.core.security import hash_password
from app.domains.ecm.models import ChangeBoardReview, ChangeRequest
from app.domains.identity.models import Role, User
from app.domains.knowledge.models import DocumentType, KnowledgeEmbedding
from app.domains.pdm.baselines import capture_baseline
from app.domains.pdm.mbom import derive_mbom
from app.domains.pdm.models import (
    BomEdge,
    BomType,
    CiCriticality,
    CoatingStatus,
    ComplianceStatus,
    ConfigurationBaseline,
    Declaration,
    Document,
    DocumentKind,
    DocumentRevision,
    LifecycleState,
    MakeOrBuy,
    MaterialType,
    MbomDelta,
    MbomDeltaType,
    Operation,
    Part,
    PartClass,
    PartRevision,
)
from app.domains.qms.models import (
    LabTestRecord,
    NonConformance,
    TestProtocol,
    TestSpecLimit,
    Unit,
    UnitComponent,
    UnitStatus,
)

logging.basicConfig(
    level=logging.INFO, format="%(levelname)-8s %(name)s: %(message)s"
)
logger = logging.getLogger("seed")

# Fixed clock. Nothing here reads the real time.
QMS_BASE_TIME = datetime(2026, 3, 12, 9, 0, 0, tzinfo=timezone.utc)
# The degradation run on the unit TF-24-018 is about, a year earlier.
QMS_097_BASE_TIME = datetime(2025, 4, 8, 9, 0, 0, tzinfo=timezone.utc)
QMS_SERIAL = "ECL-M-104"
RELEASE_TIME = datetime(2025, 2, 3, 10, 0, 0, tzinfo=timezone.utc)

# The day the freeze-cast lamellar matrix replaced the epoxy-bonded one.
GEOMETRY_CHANGE = date(2025, 6, 1)
# Dates the two configuration baselines are captured at, either side of it.
BASELINE_BEFORE = date(2025, 5, 1)
BASELINE_AFTER = date(2026, 1, 15)


# --------------------------------------------------------------------------
# Identity: one demo account per Change Control Board seat
# --------------------------------------------------------------------------
# The CCB needs Systems Engineering, Quality, Manufacturing and Procurement
# represented before a change order can carry, so the seed has to provide a
# person for each seat or the approval flow is undemonstrable. All share
# DEMO_USER_PASSWORD.
USERS: list[dict] = [
    {
        "email": "admin@magnotherm.test",
        "full_name": "Admin",
        "roles": [Role.ADMIN.value],
    },
    {
        "email": "sysenq@magnotherm.test",
        "full_name": "Sofia Brandt — Systems Engineering",
        "roles": [Role.ENGINEER.value, Role.SYSTEMS_ENGINEERING.value],
    },
    {
        "email": "quality@magnotherm.test",
        "full_name": "Jonas Weiss — Quality",
        "roles": [Role.QUALITY.value],
    },
    {
        "email": "manufacturing@magnotherm.test",
        "full_name": "Aiko Tanaka — Manufacturing",
        "roles": [Role.MANUFACTURING.value],
    },
    {
        "email": "procurement@magnotherm.test",
        "full_name": "Marek Nowak — Procurement",
        "roles": [Role.PROCUREMENT.value],
    },
    {
        "email": "controlling@magnotherm.test",
        "full_name": "Lena Fischer — Controlling",
        "roles": [Role.CONTROLLER.value],
    },
    {
        "email": "engineer@magnotherm.test",
        "full_name": "Rahul Menon — Design Engineering",
        "roles": [Role.ENGINEER.value],
    },
]


# --------------------------------------------------------------------------
# PDM: the ECLIPSE 1kW part master
# --------------------------------------------------------------------------

PARTS: list[dict] = [
    {
        "part_number": "ECL-SYS-1000",
        "description": "ECLIPSE 1kW Retail Chiller — magnetocaloric cooling system, "
        "refrigerant-free, water/alcohol transfer medium at atmospheric pressure.",
        "material_type": MaterialType.ASSEMBLY,
        "coating_status": CoatingStatus.NOT_APPLICABLE,
        "part_class": PartClass.ASSEMBLY,
        "make_or_buy": MakeOrBuy.MAKE,
        "is_configuration_item": True,
        "ci_criticality": CiCriticality.CRITICAL,
        "pfas_free": Declaration.YES,
        "contains_heavy_rare_earth": Declaration.NO,
        "rohs_reach_status": ComplianceStatus.COMPLIANT,
        "gwp_direct": 0.0,
        "revision": "C",
    },
    {
        "part_number": "ECL-AMR-200",
        "description": "Active Magnetic Regenerator Module — houses the "
        "magnetocaloric bed and the rotating magnet assembly that drives the AMR cycle.",
        "material_type": MaterialType.ASSEMBLY,
        "coating_status": CoatingStatus.NOT_APPLICABLE,
        "part_class": PartClass.ASSEMBLY,
        "make_or_buy": MakeOrBuy.MAKE,
        "is_configuration_item": True,
        "ci_criticality": CiCriticality.CRITICAL,
        "pfas_free": Declaration.YES,
        "contains_heavy_rare_earth": Declaration.NO,
        "rohs_reach_status": ComplianceStatus.COMPLIANT,
        "gwp_direct": 0.0,
        "revision": "B",
    },
    {
        "part_number": "LFS-POR-010",
        "description": "LaFeSi Porous Matrix — freeze-cast lamellar channels, 0.4 mm "
        "characteristic dimension, anti-corrosion coated. The magnetocaloric working "
        "material: heats on magnetisation, cools on demagnetisation.",
        "material_type": MaterialType.LAFESI,
        "coating_status": CoatingStatus.ANTI_CORROSION_METAL,
        "part_class": PartClass.RAW_MATERIAL,
        "make_or_buy": MakeOrBuy.MAKE,
        "standard_cost": Decimal("184.5000"),
        "lead_time_days": 45,
        "is_configuration_item": True,
        "ci_criticality": CiCriticality.CRITICAL,
        "pfas_free": Declaration.YES,
        "contains_heavy_rare_earth": Declaration.NO,
        "rohs_reach_status": ComplianceStatus.COMPLIANT,
        "gwp_direct": 0.0,
        "revision": "D",
    },
    {
        "part_number": "LFS-POR-009",
        "description": "LaFeSi Porous Matrix — epoxy-bonded packed particle bed "
        "(SUPERSEDED by LFS-POR-010 under ECO-24-005; retained for units built "
        "before the change).",
        "material_type": MaterialType.LAFESI,
        "coating_status": CoatingStatus.EPOXY_BONDED,
        "part_class": PartClass.RAW_MATERIAL,
        "make_or_buy": MakeOrBuy.MAKE,
        "standard_cost": Decimal("171.0000"),
        "lead_time_days": 45,
        "is_configuration_item": True,
        "ci_criticality": CiCriticality.HIGH,
        "pfas_free": Declaration.YES,
        "contains_heavy_rare_earth": Declaration.NO,
        "rohs_reach_status": ComplianceStatus.COMPLIANT,
        "gwp_direct": 0.0,
        "revision": "C",
    },
    {
        "part_number": "MAG-ND-050",
        "description": "Neodymium Permanent Magnet Array — rotational setup, recovers "
        "work across the magnetisation cycle for up to 30% higher efficiency. "
        "Specified without heavy rare earth elements to stay clear of export "
        "restrictions.",
        "material_type": MaterialType.NEODYMIUM,
        "coating_status": CoatingStatus.PASSIVATED,
        "part_class": PartClass.MECHANICAL,
        "make_or_buy": MakeOrBuy.BUY,
        "standard_cost": Decimal("612.0000"),
        "lead_time_days": 90,
        "is_configuration_item": True,
        "ci_criticality": CiCriticality.CRITICAL,
        "pfas_free": Declaration.YES,
        "contains_heavy_rare_earth": Declaration.NO,
        "rohs_reach_status": ComplianceStatus.COMPLIANT,
        "gwp_direct": 0.0,
        "revision": "B",
    },
    {
        "part_number": "MAG-ND-051",
        "description": "Thermally stabilised NdFeB Permanent Magnet Array — N48H "
        "grade with monitored edge-temperature margin, passivated surfaces and "
        "supplier-lot coercivity evidence for ECLIPSE field duty.",
        "material_type": MaterialType.NEODYMIUM,
        "coating_status": CoatingStatus.PASSIVATED,
        "part_class": PartClass.MECHANICAL,
        "make_or_buy": MakeOrBuy.BUY,
        "standard_cost": Decimal("648.0000"),
        "lead_time_days": 84,
        "is_configuration_item": True,
        "ci_criticality": CiCriticality.CRITICAL,
        "pfas_free": Declaration.YES,
        "contains_heavy_rare_earth": Declaration.NO,
        "rohs_reach_status": ComplianceStatus.COMPLIANT,
        "gwp_direct": 0.0,
        "revision": "A",
    },
    {
        "part_number": "CST-MCH-001",
        "description": "3D Printed Double Corrugated Housing — conformal flow channel "
        "geometry around the regenerator bed.",
        "material_type": MaterialType.POLYMER,
        "coating_status": CoatingStatus.UNCOATED,
        "part_class": PartClass.MECHANICAL,
        "make_or_buy": MakeOrBuy.MAKE,
        "standard_cost": Decimal("48.2000"),
        "lead_time_days": 10,
        "pfas_free": Declaration.YES,
        "contains_heavy_rare_earth": Declaration.NO,
        "rohs_reach_status": ComplianceStatus.COMPLIANT,
        "gwp_direct": 0.0,
        "revision": "A",
    },
    {
        "part_number": "HYD-PMP-100",
        "description": "Low-Pressure Hydraulic Loop — circulates the transfer medium "
        "through the regenerator below 1 bar.",
        "material_type": MaterialType.ASSEMBLY,
        "coating_status": CoatingStatus.NOT_APPLICABLE,
        "part_class": PartClass.ASSEMBLY,
        "make_or_buy": MakeOrBuy.MAKE,
        "is_configuration_item": True,
        "ci_criticality": CiCriticality.MEDIUM,
        "pfas_free": Declaration.YES,
        "contains_heavy_rare_earth": Declaration.NO,
        "rohs_reach_status": ComplianceStatus.COMPLIANT,
        "gwp_direct": 0.0,
        "revision": "A",
    },
    {
        "part_number": "FLD-WA-001",
        "description": "Water/Alcohol Transfer Medium — operating pressure < 1 bar. "
        "Zero direct GWP, PFAS-free, outside the scope of EN378.",
        "material_type": MaterialType.FLUID,
        "coating_status": CoatingStatus.NOT_APPLICABLE,
        "part_class": PartClass.CONSUMABLE,
        "unit_of_measure": "L",
        "make_or_buy": MakeOrBuy.BUY,
        "standard_cost": Decimal("3.4000"),
        "lead_time_days": 5,
        "pfas_free": Declaration.YES,
        "contains_heavy_rare_earth": Declaration.NO,
        "rohs_reach_status": ComplianceStatus.COMPLIANT,
        "gwp_direct": 0.0,
        "revision": "A",
    },
    {
        # The compliance gap, on purpose. A bought-in elastomer whose supplier
        # declaration has not come back is exactly how a PFAS claim fails to be
        # provable in practice.
        "part_number": "SEA-ORG-004",
        "description": "O-ring seal, EPDM 70 Shore A, 24×2 mm — hydraulic circuit "
        "and regenerator end caps. Supplier PFAS declaration outstanding.",
        "material_type": MaterialType.COMPOSITE,
        "coating_status": CoatingStatus.NOT_APPLICABLE,
        "part_class": PartClass.MECHANICAL,
        "make_or_buy": MakeOrBuy.BUY,
        "standard_cost": Decimal("0.3800"),
        "lead_time_days": 14,
        "pfas_free": Declaration.UNKNOWN,
        "contains_heavy_rare_earth": Declaration.NO,
        "rohs_reach_status": ComplianceStatus.UNKNOWN,
        "gwp_direct": None,
        "revision": "A",
    },
    {
        "part_number": "PKG-CRT-001",
        "description": "Export crate with moulded foam inserts, ISPM-15 heat treated. "
        "Manufacturing only — no engineering function.",
        "material_type": MaterialType.COMPOSITE,
        "coating_status": CoatingStatus.NOT_APPLICABLE,
        "part_class": PartClass.PACKAGING,
        "make_or_buy": MakeOrBuy.BUY,
        "standard_cost": Decimal("62.0000"),
        "lead_time_days": 7,
        "pfas_free": Declaration.YES,
        "contains_heavy_rare_earth": Declaration.NO,
        "rohs_reach_status": ComplianceStatus.EXEMPT,
        "gwp_direct": 0.0,
        "revision": "A",
    },
    {
        "part_number": "CST-ADH-002",
        "description": "Structural adhesive, two-part epoxy — bonds the corrugated "
        "housing halves. Consumed on the line; not modelled on the drawing.",
        "material_type": MaterialType.COMPOSITE,
        "coating_status": CoatingStatus.NOT_APPLICABLE,
        "part_class": PartClass.CONSUMABLE,
        "unit_of_measure": "kg",
        "make_or_buy": MakeOrBuy.BUY,
        "standard_cost": Decimal("94.0000"),
        "lead_time_days": 21,
        "pfas_free": Declaration.YES,
        "contains_heavy_rare_earth": Declaration.NO,
        "rohs_reach_status": ComplianceStatus.COMPLIANT,
        "gwp_direct": 0.0,
        "revision": "A",
    },
]

# (parent, child, quantity, find_number, uom, effective_from, effective_to)
EBOM_EDGES: list[tuple[str, str, str, str, str, date | None, date | None]] = [
    ("ECL-SYS-1000", "ECL-AMR-200", "1", "100", "ea", None, None),
    ("ECL-SYS-1000", "HYD-PMP-100", "1", "200", "ea", None, None),
    # The geometry change, expressed as effectivity rather than as a deletion:
    # units built before 2025-06-01 genuinely contain the epoxy-bonded bed, and
    # their service records have to keep resolving to it.
    ("ECL-AMR-200", "LFS-POR-009", "6", "110", "ea", None, GEOMETRY_CHANGE),
    ("ECL-AMR-200", "LFS-POR-010", "8", "111", "ea", GEOMETRY_CHANGE, None),
    ("ECL-AMR-200", "MAG-ND-050", "1", "120", "ea", None, None),
    ("ECL-AMR-200", "CST-MCH-001", "2", "130", "ea", None, None),
    ("ECL-AMR-200", "SEA-ORG-004", "4", "140", "ea", None, None),
    ("HYD-PMP-100", "FLD-WA-001", "1", "210", "ea", None, None),
    ("HYD-PMP-100", "SEA-ORG-004", "2", "220", "ea", None, None),
]

# Where the manufacturing view departs from the design view, and why.
MBOM_DELTAS: list[dict] = [
    {
        "sequence": 10,
        "delta_type": MbomDeltaType.REQUANTIFY,
        "parent_part": "HYD-PMP-100",
        "child_part": "FLD-WA-001",
        "quantity": Decimal("1.8000"),
        "unit_of_measure": "L",
        "rationale": "Final charge volume including purge and priming losses. The "
        "drawing calls out the fluid as a single item; the line has to issue a "
        "measured 1.8 L.",
    },
    {
        "sequence": 20,
        "delta_type": MbomDeltaType.ADD,
        "parent_part": "ECL-AMR-200",
        "child_part": "CST-ADH-002",
        "quantity": Decimal("0.1500"),
        "unit_of_measure": "kg",
        "operation_seq": 20,
        "rationale": "Two-part epoxy for bonding the housing halves. Consumed at "
        "assembly and absent from the EBOM because it is not a designed component.",
    },
    {
        "sequence": 30,
        "delta_type": MbomDeltaType.ADD,
        "parent_part": None,  # root
        "child_part": "PKG-CRT-001",
        "quantity": Decimal("1.0000"),
        "unit_of_measure": "ea",
        "operation_seq": 40,
        "rationale": "Export crate. Shipping configuration, not product function.",
    },
    {
        "sequence": 40,
        "delta_type": MbomDeltaType.PHANTOM,
        "parent_part": None,
        "child_part": "HYD-PMP-100",
        "is_phantom": True,
        "rationale": "The hydraulic loop is kitted and issued pre-assembled rather "
        "than stocked as a separate item, so it is exploded through on the floor.",
    },
    {
        "sequence": 50,
        "delta_type": MbomDeltaType.REQUANTIFY,
        "parent_part": "ECL-AMR-200",
        "child_part": "SEA-ORG-004",
        "quantity": Decimal("4.0000"),
        "unit_of_measure": "ea",
        "scrap_factor": Decimal("0.0500"),
        "rationale": "5% scrap allowance: the end-cap O-rings are routinely nicked "
        "on installation and are cheap enough not to reclaim.",
    },
]

OPERATIONS: list[dict] = [
    {
        "op_seq": 10,
        "work_center": "WC-COAT-01",
        "description": "Apply anti-corrosion metal coating to the LaFeSi matrix and "
        "cure at 180 °C for 40 minutes. Iron-based magnetocaloric material corrodes "
        "in the water/alcohol circuit if this is skipped.",
        "setup_minutes": Decimal("25.00"),
        "run_minutes": Decimal("40.00"),
    },
    {
        "op_seq": 20,
        "work_center": "WC-ASSY-02",
        "description": "Bond the corrugated housing halves, load the regenerator bed, "
        "and fit the rotational magnet array.",
        "setup_minutes": Decimal("15.00"),
        "run_minutes": Decimal("95.00"),
    },
    {
        "op_seq": 30,
        "work_center": "WC-FILL-01",
        "description": "Charge the hydraulic loop with the water/alcohol medium, purge, "
        "and leak test below 1 bar.",
        "setup_minutes": Decimal("10.00"),
        "run_minutes": Decimal("35.00"),
    },
    {
        "op_seq": 40,
        "work_center": "WC-TEST-01",
        "description": "Run the acceptance test to protocol, record the temperature "
        "span, and pack for export.",
        "setup_minutes": Decimal("5.00"),
        "run_minutes": Decimal("60.00"),
    },
]

# Controlled files. Seeded with real bytes so the vault, the content hashing and
# the download path are exercised rather than merely wired up.
DOCUMENTS: list[dict] = [
    {
        "document_number": "WI-COAT-001",
        "title": "Work instruction — anti-corrosion coating and cure",
        "kind": DocumentKind.WORK_INSTRUCTION,
        "related_part": "LFS-POR-010",
        "filename": "WI-COAT-001.md",
        "content_type": "text/markdown",
        "body": (
            "# WI-COAT-001 — Anti-corrosion coating\n\n"
            "1. Degrease the matrix in the ultrasonic bath, 8 minutes.\n"
            "2. Apply the metal coating to 12-18 um.\n"
            "3. Cure at 180 C for 40 minutes. Do not exceed 195 C: the "
            "Curie point of the LaFeSi composition sits just above it and the "
            "magnetocaloric effect degrades irreversibly.\n"
            "4. Inspect for pinholes under 10x magnification.\n"
        ),
    },
    {
        "document_number": "DRW-AMR-200",
        "title": "Assembly drawing — Active Magnetic Regenerator module",
        "kind": DocumentKind.DRAWING,
        "related_part": "ECL-AMR-200",
        "filename": "DRW-AMR-200.svg",
        "content_type": "image/svg+xml",
        "body": (
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 240 120">'
            '<rect x="10" y="10" width="220" height="100" fill="none" '
            'stroke="currentColor"/>'
            '<circle cx="80" cy="60" r="30" fill="none" stroke="currentColor"/>'
            '<text x="120" y="64" font-size="9">AMR bed / magnet array</text>'
            "</svg>"
        ),
    },
]


# --------------------------------------------------------------------------
# QMS: two built units, one that passes and one that does not
# --------------------------------------------------------------------------
# The two units are the same product built ten months apart, either side of the
# freeze-cast change, and they carry different material lots. That is what makes
# the traceability questions answerable: forwards ("what is in ECL-M-104?"),
# backwards ("which units have magnets from lot MAG-L-2312?"), and the link
# between a failing measurement and the batch it came from.
UNIT_BUILDS: list[dict] = [
    {
        "serial": "ECL-M-097",
        "part": "ECL-AMR-200",
        # Before 2025-06-01, so the build record picks up the epoxy-bonded bed.
        "built_at": datetime(2025, 3, 18, 8, 30, tzinfo=timezone.utc),
        "as_of": date(2025, 3, 18),
        "plant": "Darmstadt",
        "lots": {
            "LFS-POR-009": "LFS-L-2312",
            "MAG-ND-050": "MAG-L-2312",
            "CST-MCH-001": "PLA-L-2311",
            "SEA-ORG-004": "SEA-L-2401",
        },
    },
    {
        "serial": "ECL-M-104",
        "part": "ECL-AMR-200",
        "built_at": datetime(2026, 2, 20, 9, 15, tzinfo=timezone.utc),
        "as_of": None,
        "plant": "Darmstadt",
        "lots": {
            "LFS-POR-010": "LFS-L-2405",
            "MAG-ND-050": "MAG-L-2508",
            "CST-MCH-001": "PLA-L-2502",
            "SEA-ORG-004": "SEA-L-2451",
        },
    },
]

# The acceptance protocol these readings are judged against. The 15.0 K floor is
# what turns TF-24-018's "0.9 K span collapse" from a note into a failed test.
TEST_PROTOCOL: dict = {
    "code": "TP-ECL-1K",
    "revision": "A",
    "name": "ECLIPSE 1kW regenerator acceptance test",
    "applies_to_part": "ECL-AMR-200",
    "description": (
        "Steady-state acceptance run at a 2.5 Hz drive frequency. Pressure drop "
        "is bounded above only: sustained readings over 900 mbar indicate bed "
        "fouling, and there is no lower bound worth setting."
    ),
    "limits": [
        ("temperature_span_delta_K", 15.0, 18.0, 16.0),
        ("pressure_drop_mbar", None, 900.0, 850.0),
        ("magnetization_cycles_hz", 2.4, 2.6, 2.5),
        ("cooling_capacity_W", 950.0, None, 1000.0),
    ],
}

# temperature_span_delta_K fluctuates across 15.2 .. 16.1; pressure drop sits
# around 850 mbar; the drive frequency is a 2.5 Hz setpoint, so it is constant
# by design rather than noisy. Cooling capacity tracks the temperature span.
QMS_SAMPLES: list[dict] = [
    {"span": 15.2, "pressure": 848.0, "hz": 2.5, "watts": 985.0},
    {"span": 15.6, "pressure": 851.5, "hz": 2.5, "watts": 1002.0},
    {"span": 16.1, "pressure": 853.0, "hz": 2.5, "watts": 1031.0},
    {"span": 15.8, "pressure": 849.2, "hz": 2.5, "watts": 1014.0},
    {"span": 15.4, "pressure": 850.6, "hz": 2.5, "watts": 994.0},
]

# ECL-M-097 as described in TF-24-018: healthy at first, then the span collapses
# below the acceptance floor after roughly 400 hours on the magnet from lot
# MAG-L-2312. The last two readings fail, and the record says which metric and
# against which limit.
QMS_SAMPLES_097: list[dict] = [
    {"span": 15.8, "pressure": 842.0, "hz": 2.5, "watts": 1011.0},
    {"span": 15.5, "pressure": 845.0, "hz": 2.5, "watts": 998.0},
    {"span": 15.1, "pressure": 851.0, "hz": 2.5, "watts": 972.0},
    {"span": 14.9, "pressure": 858.0, "hz": 2.5, "watts": 944.0},
    {"span": 14.6, "pressure": 869.0, "hz": 2.5, "watts": 921.0},
]


# --------------------------------------------------------------------------
# Knowledge corpus
# --------------------------------------------------------------------------

KNOWLEDGE_DOCS: list[dict] = [
    {
        "source_ref": "ECO-24-005",
        "document_type": DocumentType.ECO,
        "related_part": "LFS-POR-010",
        "text_content": (
            "ECO-24-005 [LFS-POR-010]: Transitioned from epoxy-bonded AMR "
            "geometries to non-bonded, freeze-cast lamellar channels for the "
            "LaFeSi matrix. Resulted in a 12% improvement in conjugate heat "
            "transfer and lower flow resistance. Effective 2025-06-01; units "
            "built before that date retain LFS-POR-009."
        ),
    },
    {
        "source_ref": "TF-24-018",
        "document_type": DocumentType.TEST_FAILURE,
        "related_part": "MAG-ND-050",
        "text_content": (
            "TF-24-018 [MAG-ND-050]: Unit ECL-M-097 showed a 0.9 K temperature "
            "span collapse after 400 hours. Root cause traced to partial "
            "demagnetisation at the array edge where operating temperature "
            "exceeded the grade's rated ceiling. Corrective action: switch to a "
            "higher intrinsic coercivity grade and add a passivation layer. "
            "Verified on ECL-M-104, which has held span between 15.2 and 16.1 K."
        ),
    },
    {
        "source_ref": "SPEC-ECL-1K-R3",
        "document_type": DocumentType.SPEC,
        "related_part": "FLD-WA-001",
        "text_content": (
            "SPEC-ECL-1K-R3 [FLD-WA-001]: The ECLIPSE 1kW platform circulates a "
            "water/alcohol transfer medium at below 1 bar. Because the system "
            "carries no explosive or toxic refrigerant gas, it has zero direct "
            "GWP, is PFAS-free, and falls outside the scope of EN378. Pressure "
            "drop across the regenerator is specified at 850 mbar nominal; "
            "sustained readings above 900 mbar indicate bed fouling."
        ),
    },
    {
        "source_ref": "SUP-24-031",
        "document_type": DocumentType.FIELD_REPORT,
        "related_part": "SEA-ORG-004",
        "text_content": (
            "SUP-24-031 [SEA-ORG-004]: Supplier PFAS/REACH declaration for the "
            "EPDM O-ring is still outstanding after two requests. Until it "
            "arrives the ECLIPSE PFAS-free claim cannot be evidenced down to "
            "component level, even though every other item in the bill of "
            "materials is declared. Procurement to escalate or qualify a second "
            "source."
        ),
    },
]


async def seed() -> dict[str, int]:
    await init_database()

    provider = get_embedding_provider()
    session_factory = get_session_factory()

    async with session_factory() as session:
        # Idempotency: clear the tables this script owns before rebuilding.
        await session.execute(
            text(
                "TRUNCATE TABLE document_chunks, source_document_versions, source_documents, "
                "cost_rollup_snapshots, cost_targets, actuals, commitments, budgets, cost_centres, work_centre_rates, "
                "timesheet_entries, resource_allocations, engineer_capacity, test_asset_usage, asset_bookings, calibration_certificates, lab_assets, "
                "milestones, deliverables, consortium_partners, trl_gates, work_packages, programs, field_events, deployed_units, customer_sites, crm_opportunities, crm_leads, "
                "stock_positions, receipt_lots, goods_receipts, purchase_order_lines, purchase_orders, suppliers, webhook_inbox, integration_outbox, external_references, "
                "automation_findings, eval_case_results, eval_runs, tool_invocations, agent_runs, access_token_revocations, refresh_sessions, "
                "knowledge_embeddings, lab_test_records, "
                "configuration_baselines, mbom_deltas, operations, bom_edges, "
                "document_revisions, documents, part_revisions, parts, users, "
                "agent_proposals, audit_events, change_notice_acknowledgements, "
                "change_notices, change_order_lines, change_orders, "
                "impact_assessments, change_board_reviews, change_affected_items, "
                "change_requests, capa_actions, non_conformances, unit_components, "
                "units, test_spec_limits, test_protocols RESTART IDENTITY CASCADE"
            )
        )

        # --- Users ---------------------------------------------------------
        # One Argon2 hash reused across the demo accounts. Hashing seven times
        # would cost ~0.4s to produce seven identical-strength hashes of the
        # same password, which buys nothing on synthetic accounts.
        demo_hash = hash_password(get_settings().demo_user_password)
        for spec in USERS:
            session.add(User(**spec, password_hash=demo_hash, is_active=True))
        logger.info("Inserted %d demo users.", len(USERS))

        # --- Parts and their initial revisions -------------------------------
        parts: dict[str, Part] = {}
        revisions: dict[str, PartRevision] = {}
        for spec in PARTS:
            attributes = {k: v for k, v in spec.items() if k != "revision"}
            part = Part(**attributes)
            session.add(part)
            parts[spec["part_number"]] = part
        await session.flush()  # assign PKs before building revisions

        for spec in PARTS:
            revision = PartRevision(
                part_id=parts[spec["part_number"]].id,
                revision=spec["revision"],
                lifecycle_state=LifecycleState.RELEASED,
                released_at=RELEASE_TIME,
                change_summary="Initial release of the record in the PDM system.",
            )
            session.add(revision)
            revisions[spec["part_number"]] = revision
        await session.flush()
        logger.info("Inserted %d parts and %d revisions.", len(parts), len(revisions))

        # --- EBOM ------------------------------------------------------------
        for parent, child, quantity, find, uom, valid_from, valid_to in EBOM_EDGES:
            session.add(
                BomEdge(
                    parent_revision_id=revisions[parent].id,
                    child_part_id=parts[child].id,
                    bom_type=BomType.EBOM,
                    quantity=Decimal(quantity),
                    unit_of_measure=uom,
                    find_number=find,
                    effective_from=valid_from,
                    effective_to=valid_to,
                )
            )
        logger.info("Inserted %d EBOM edges.", len(EBOM_EDGES))

        # --- Manufacturing deltas and routing --------------------------------
        root_revision = revisions["ECL-SYS-1000"]
        for spec in MBOM_DELTAS:
            session.add(
                MbomDelta(
                    root_revision_id=root_revision.id,
                    sequence=spec["sequence"],
                    delta_type=spec["delta_type"],
                    parent_part_id=(
                        parts[spec["parent_part"]].id if spec["parent_part"] else None
                    ),
                    child_part_id=(
                        parts[spec["child_part"]].id if spec.get("child_part") else None
                    ),
                    quantity=spec.get("quantity"),
                    unit_of_measure=spec.get("unit_of_measure"),
                    operation_seq=spec.get("operation_seq"),
                    is_phantom=spec.get("is_phantom"),
                    scrap_factor=spec.get("scrap_factor"),
                    rationale=spec["rationale"],
                )
            )
        for spec in OPERATIONS:
            session.add(Operation(root_revision_id=root_revision.id, **spec))
        logger.info(
            "Inserted %d MBOM deltas and %d routing operations.",
            len(MBOM_DELTAS),
            len(OPERATIONS),
        )

        # --- Test protocol ----------------------------------------------------
        # Before the units, because the readings are judged as they are written.
        protocol = TestProtocol(
            code=TEST_PROTOCOL["code"],
            revision=TEST_PROTOCOL["revision"],
            name=TEST_PROTOCOL["name"],
            description=TEST_PROTOCOL["description"],
            applies_to_part_id=parts[TEST_PROTOCOL["applies_to_part"]].id,
            is_active=True,
        )
        session.add(protocol)
        await session.flush()
        for metric, lower, upper, target in TEST_PROTOCOL["limits"]:
            session.add(
                TestSpecLimit(
                    protocol_id=protocol.id,
                    metric=metric,
                    lower_limit=lower,
                    upper_limit=upper,
                    target=target,
                )
            )
        logger.info(
            "Inserted protocol %s with %d limits.",
            protocol.label,
            len(TEST_PROTOCOL["limits"]),
        )

        # --- Knowledge corpus -------------------------------------------------
        vectors = await provider.embed([doc["text_content"] for doc in KNOWLEDGE_DOCS])
        for doc, vector in zip(KNOWLEDGE_DOCS, vectors, strict=True):
            related = parts.get(doc["related_part"])
            session.add(
                KnowledgeEmbedding(
                    embedding=vector,
                    related_part_id=related.id if related else None,
                    document_type=doc["document_type"],
                    text_content=doc["text_content"],
                    source_ref=doc["source_ref"],
                )
            )
        logger.info(
            "Inserted %d knowledge documents (embedding provider: %s).",
            len(KNOWLEDGE_DOCS),
            provider.name,
        )

        await session.commit()

    # --- Document vault ---------------------------------------------------
    # After the commit, because check-in writes bytes through the FileStore and
    # a rollback would leave the object store holding files no row points at.
    await _seed_documents()

    # --- Derived and captured data ----------------------------------------
    # Both run through the real services rather than inserting rows directly:
    # if `derive_mbom` or `capture_baseline` is broken, seeding should fail
    # rather than paper over it with hand-built fixtures.
    async with session_factory() as session:
        await derive_mbom(
            session, actor=SYSTEM_PRINCIPAL, part_number="ECL-SYS-1000", commit=True
        )

    async with session_factory() as session:
        await capture_baseline(
            session,
            actor=SYSTEM_PRINCIPAL,
            part_number="ECL-SYS-1000",
            name="ECLIPSE 1kW — pre freeze-cast (2025-05)",
            platform="ECLIPSE",
            as_of=BASELINE_BEFORE,
            notes="Configuration as it stood before ECO-24-005 took effect.",
        )
        await capture_baseline(
            session,
            actor=SYSTEM_PRINCIPAL,
            part_number="ECL-SYS-1000",
            name="ECLIPSE 1kW — post freeze-cast (2026-01)",
            platform="ECLIPSE",
            as_of=BASELINE_AFTER,
            notes="Configuration after the freeze-cast lamellar matrix phased in.",
        )

    # --- Built units, their genealogy, and their measurements ---------------
    # After the MBOM and the baselines: a build record is a snapshot of the
    # manufacturing structure, so there has to be one to snapshot, and the unit
    # records which captured baseline it was taken from.
    await _seed_units()

    # --- A change part-way through the board --------------------------------
    await _seed_change_request()

    # --- A non-conformance against a material lot ---------------------------
    await _seed_non_conformance()

    # --- Approved corrective change linked back to the lot NCR -------------
    magnet_ecr = await _seed_magnet_change()

    # --- Back-office, commercial, program and controlling showcase ---------
    await _seed_enterprise(magnet_ecr)

    # --- Agent proposals awaiting a human, and one recorded eval run -------
    await _seed_governance()

    # Built after seeding: IVFFlat clusters on the rows present at creation.
    await create_vector_index()

    async with session_factory() as session:
        counts = {
            "users": await session.scalar(select(func.count()).select_from(User)),
            "parts": await session.scalar(select(func.count()).select_from(Part)),
            "part_revisions": await session.scalar(
                select(func.count()).select_from(PartRevision)
            ),
            "ebom_edges": await session.scalar(
                select(func.count())
                .select_from(BomEdge)
                .where(BomEdge.bom_type == BomType.EBOM)
            ),
            "mbom_edges": await session.scalar(
                select(func.count())
                .select_from(BomEdge)
                .where(BomEdge.bom_type == BomType.MBOM)
            ),
            "mbom_deltas": await session.scalar(
                select(func.count()).select_from(MbomDelta)
            ),
            "operations": await session.scalar(
                select(func.count()).select_from(Operation)
            ),
            "baselines": await session.scalar(
                select(func.count()).select_from(ConfigurationBaseline)
            ),
            "documents": await session.scalar(
                select(func.count()).select_from(Document)
            ),
            "document_revisions": await session.scalar(
                select(func.count()).select_from(DocumentRevision)
            ),
            "change_requests": await session.scalar(
                select(func.count()).select_from(ChangeRequest)
            ),
            "board_reviews": await session.scalar(
                select(func.count()).select_from(ChangeBoardReview)
            ),
            "units": await session.scalar(select(func.count()).select_from(Unit)),
            "unit_components": await session.scalar(
                select(func.count()).select_from(UnitComponent)
            ),
            "non_conformances": await session.scalar(
                select(func.count()).select_from(NonConformance)
            ),
            "lab_test_records": await session.scalar(
                select(func.count()).select_from(LabTestRecord)
            ),
            "knowledge_embeddings": await session.scalar(
                select(func.count())
                .select_from(KnowledgeEmbedding)
                .where(KnowledgeEmbedding.embedding.isnot(None))
            ),
        }
    return counts


async def _principal_for(session, email: str) -> Principal:
    """Act as a seeded user, so the record attributes the work to a person."""
    user = (
        await session.execute(select(User).where(User.email == email))
    ).scalar_one()
    return Principal(
        actor_type=ActorType.HUMAN,
        user_id=user.id,
        email=user.email,
        roles=tuple(user.roles),
    )


async def _seed_units() -> None:
    """Build the two units, then record their measurements against the protocol.

    The readings go in through `evaluate`, the same function the application
    uses, so the pass/fail verdicts in the seeded data are produced rather than
    asserted. ECL-M-097's last two samples fall below the 15.0 K floor and are
    stored as failures with the breach recorded against them.
    """
    from app.domains.qms.service import build_unit, evaluate

    session_factory = get_session_factory()
    for spec in UNIT_BUILDS:
        async with session_factory() as session:
            result = await build_unit(
                session,
                actor=SYSTEM_PRINCIPAL,
                serial_number=spec["serial"],
                part_number=spec["part"],
                lots=spec["lots"],
                plant=spec["plant"],
                built_at=spec["built_at"],
                as_of=spec["as_of"],
            )
            logger.info(
                "Built %s: %d components from the %s, %d lots assigned.",
                result.serial_number,
                result.components_recorded,
                result.bom_type_used,
                result.lots_assigned,
            )

    async with session_factory() as session:
        protocol = (
            await session.execute(
                select(TestProtocol)
                .where(TestProtocol.code == TEST_PROTOCOL["code"])
                .options(selectinload(TestProtocol.limits))
            )
        ).scalar_one()

        for serial, samples, base_time in [
            ("ECL-M-104", QMS_SAMPLES, QMS_BASE_TIME),
            ("ECL-M-097", QMS_SAMPLES_097, QMS_097_BASE_TIME),
        ]:
            unit = (
                await session.execute(select(Unit).where(Unit.serial_number == serial))
            ).scalar_one()
            for index, sample in enumerate(samples):
                record = LabTestRecord(
                    unit_id=unit.id,
                    recorded_at=base_time + timedelta(hours=index),
                    temperature_span_delta_K=sample["span"],
                    pressure_drop_mbar=sample["pressure"],
                    magnetization_cycles_hz=sample["hz"],
                    cooling_capacity_W=sample["watts"],
                    protocol_id=protocol.id,
                    test_rig="RIG-DA-02",
                    operator="lab.darmstadt",
                )
                record.result, record.breaches = evaluate(record, protocol)
                session.add(record)
            logger.info("Inserted %d test records for %s.", len(samples), serial)

        # ECL-M-097 is the unit TF-24-018 is about: it went out, degraded, and
        # came back.
        failing = (
            await session.execute(select(Unit).where(Unit.serial_number == "ECL-M-097"))
        ).scalar_one()
        failing.status = UnitStatus.RMA
        failing.customer_ref = "Retail pilot, Frankfurt"

        shipped = (
            await session.execute(select(Unit).where(Unit.serial_number == "ECL-M-104"))
        ).scalar_one()
        shipped.status = UnitStatus.IN_FIELD
        shipped.customer_ref = "Retail pilot, Darmstadt"

        await session.commit()


async def _seed_non_conformance() -> None:
    """One lot-scoped non-conformance, with its affected units derived.

    Raised against the magnet lot rather than against the unit that failed.
    That is the point: the system works out for itself which articles carry
    material from that batch, instead of relying on whoever raised it to
    remember.
    """
    from app.domains.qms import ncr as ncr_service
    from app.domains.qms.models import CapaKind, NcrSeverity, NcrSource

    session_factory = get_session_factory()
    async with session_factory() as session:
        quality = await _principal_for(session, "quality@magnotherm.test")
        report = await ncr_service.raise_non_conformance(
            session,
            actor=quality,
            title="Partial demagnetisation at the magnet array edge",
            description=(
                "ECL-M-097 lost 0.9 K of temperature span after roughly 400 hours "
                "and now fails the 15.0 K acceptance floor on TP-ECL-1K. Root "
                "cause traced to partial demagnetisation at the array edge, where "
                "the operating temperature exceeded the grade's rated ceiling. "
                "Scoped to magnet lot MAG-L-2312 rather than to the single unit, "
                "because every article built from that batch is equally suspect."
            ),
            source=NcrSource.FIELD,
            severity=NcrSeverity.MAJOR,
            lot_number="MAG-L-2312",
        )

    async with session_factory() as session:
        quality = await _principal_for(session, "quality@magnotherm.test")
        await ncr_service.add_action(
            session,
            actor=quality,
            number=report.number,
            kind=CapaKind.CORRECTIVE,
            description=(
                "Replace the magnet array on every affected unit with a higher "
                "intrinsic coercivity grade and add a passivation layer."
            ),
            owner_label="Jonas Weiss — Quality",
            due_date=date(2026, 9, 30),
        )
        await ncr_service.add_action(
            session,
            actor=quality,
            number=report.number,
            kind=CapaKind.PREVENTIVE,
            description=(
                "Add an edge-temperature check to incoming inspection for NdFeB "
                "arrays, and record the grade against the lot."
            ),
            owner_label="Marek Nowak — Procurement",
            due_date=date(2026, 10, 31),
        )

    logger.info(
        "Raised %s against lot MAG-L-2312 with 2 open actions.", report.number
    )


async def _seed_change_request() -> None:
    """One live change request, part-way through Change Control Board review.

    Deliberately the O-ring: it is the component whose missing PFAS declaration
    makes the ECLIPSE compliance claim unprovable, so the change process is
    shown reacting to something the product data itself surfaced rather than to
    an invented problem. Two of four seats have voted, which leaves the quorum
    tracker with something to show.
    """
    from app.domains.ecm import service as ecm
    from app.domains.ecm.models import ChangeOrigin, ChangePriority, ReviewDecision

    session_factory = get_session_factory()
    async with session_factory() as session:
        procurement = await _principal_for(session, "procurement@magnotherm.test")
        request = await ecm.create_change_request(
            session,
            actor=procurement,
            title="Qualify a second source for the EPDM O-ring with a PFAS declaration",
            problem_statement=(
                "SEA-ORG-004 has no supplier PFAS or REACH declaration after two "
                "requests (SUP-24-031). Every other item in the ECLIPSE bill of "
                "materials is declared, so this single component is what stops the "
                "PFAS-free claim from being evidenced down to component level."
            ),
            proposed_solution=(
                "Qualify an alternate EPDM supplier that will provide a full "
                "declaration, and supersede SEA-ORG-004 once first articles pass "
                "the hydraulic circuit leak test."
            ),
            affected_part_numbers=["SEA-ORG-004"],
            origin=ChangeOrigin.SUPPLY_CHAIN,
            priority=ChangePriority.HIGH,
            preliminary_impact=(
                "No form, fit or function change expected; the risk is qualification "
                "time on the seal, not on the system."
            ),
        )
        await ecm.submit_change_request(
            session, actor=procurement, number=request.number
        )

    async with session_factory() as session:
        for email, decision, comment in [
            (
                "sysenq@magnotherm.test",
                ReviewDecision.APPROVE,
                "No interface change. The seal groove geometry is unchanged.",
            ),
            (
                "manufacturing@magnotherm.test",
                ReviewDecision.APPROVE,
                "No tooling or routing impact; same part on the same operations.",
            ),
        ]:
            await ecm.record_review(
                session,
                actor=await _principal_for(session, email),
                number=request.number,
                decision=decision,
                comment=comment,
            )

    logger.info(
        "Raised %s over SEA-ORG-004 with 2 of 4 board seats voted.", request.number
    )
    return request.number


async def _seed_magnet_change() -> str:
    """Escalate the magnet-lot NCR through a complete four-seat CCB decision."""
    from app.domains.ecm import service as ecm
    from app.domains.ecm.models import ChangeOrigin, ChangePriority, ReviewDecision

    session_factory=get_session_factory()
    async with session_factory() as session:
        quality=await _principal_for(session,"quality@magnotherm.test")
        request=await ecm.create_change_request(
            session,
            actor=quality,
            title="Stabilise ECLIPSE magnet array edge temperature margin",
            problem_statement=(
                "NCR-26-001 traced the degraded temperature span on ECL-M-097 "
                "to partial demagnetisation of MAG-ND-050 from receipt "
                "GR-2026-0018 / lot MAG-L-2312. The last two TP-ECL-1K samples "
                "fell below the 15.0 K acceptance limit."
            ),
            proposed_solution=(
                "Replace MAG-ND-050 with thermally stabilised N48H array "
                "MAG-ND-051, require coercivity and edge-temperature evidence "
                "per supplier lot, and introduce at serial ECL-M-105."
            ),
            affected_part_numbers=["MAG-ND-050"],
            origin=ChangeOrigin.QUALITY,
            priority=ChangePriority.URGENT,
            preliminary_impact=(
                "One AMR revision, MBOM re-derivation, incoming-inspection "
                "update, affected-unit retrofit, and EUR 36 direct material "
                "increase per system before labour."
            ),
        )
        await ecm.submit_change_request(session,actor=quality,number=request.number)

    votes=[
        ("sysenq@magnotherm.test","Thermal margin and magnetic containment interfaces verified."),
        ("quality@magnotherm.test","N48H HcJ certificate and 500-hour endurance evidence accepted."),
        ("manufacturing@magnotherm.test","Same envelope and find number; work instruction update approved."),
        ("procurement@magnotherm.test","Qualified second source and lot-level certificate flow confirmed."),
    ]
    for email,comment in votes:
        async with session_factory() as session:
            await ecm.record_review(session,actor=await _principal_for(session,email),number=request.number,decision=ReviewDecision.APPROVE,comment=comment)

    async with session_factory() as session:
        report=(await session.execute(select(NonConformance).where(NonConformance.number=="NCR-26-001"))).scalar_one()
        current=(await session.execute(select(ChangeRequest).where(ChangeRequest.number==request.number))).scalar_one()
        report.escalated_ecr_id=current.id
        await session.commit()
    logger.info("Approved %s with all four CCB seats and linked NCR-26-001.",request.number)
    return request.number


async def _seed_enterprise(magnet_ecr: str) -> None:
    """Seed the cross-domain records used by the golden workflow dashboards."""
    from datetime import datetime, timedelta, timezone
    from decimal import Decimal
    from app.domains.assets.models import AssetBooking, CalibrationCertificate, LabAsset
    from app.domains.controlling.models import Actual, Budget, Commitment, CostCentre, WorkCentreRate
    from app.domains.crm.models import CustomerSite, DeployedUnit, FieldEvent, Lead, Opportunity
    from app.domains.knowledge.ingestion import ingest
    from app.domains.procurement.models import GoodsReceipt, PurchaseOrder, PurchaseOrderLine, ReceiptLot, StockPosition, Supplier
    from app.domains.programs.models import ConsortiumPartner, Deliverable, Milestone, Program, TrlGate, WorkPackage
    from app.domains.resources.models import EngineerCapacity, ResourceAllocation, TimesheetEntry

    session_factory=get_session_factory()
    async with session_factory() as session:
        parts={p.part_number:p for p in (await session.execute(select(Part))).scalars()}
        users={u.email:u for u in (await session.execute(select(User))).scalars()}
        units={u.serial_number:u for u in (await session.execute(select(Unit))).scalars()}
        supplier=Supplier(code="SUP-NDM-01",name="Rhine Magnetics GmbH",lead_time_days=84,quality_rating=92.5); session.add(supplier); await session.flush()
        po=PurchaseOrder(order_number="PO-2026-0042",supplier_id=supplier.id,status="partially_received",ordered_at=date(2026,7,1),required_date=date(2026,9,23)); session.add(po); await session.flush()
        line=PurchaseOrderLine(purchase_order_id=po.id,line_number=10,part_id=parts["MAG-ND-050"].id,quantity=Decimal("12"),received_quantity=Decimal("6"),unit_price=Decimal("612")); session.add(line); await session.flush()
        receipt=GoodsReceipt(receipt_number="GR-2026-0018",purchase_order_id=po.id,received_at=datetime(2026,7,18,9,tzinfo=timezone.utc),received_by=users["procurement@magnotherm.test"].id); session.add(receipt); await session.flush()
        session.add(ReceiptLot(receipt_id=receipt.id,po_line_id=line.id,supplier_id=supplier.id,part_id=line.part_id,internal_lot="MAG-L-2312",supplier_lot="RM-2312-N48H",quantity=6,accepted_quantity=6,certificate_ref="CoC-RM-2312"))
        session.add(StockPosition(part_id=line.part_id,warehouse="Main",on_hand=2,allocated=2,reorder_level=4))
        qualified=Supplier(code="SUP-NDM-02",name="Alpine Magnetic Systems AG (synthetic)",lead_time_days=70,quality_rating=96.8); session.add(qualified); await session.flush()
        corrective_po=PurchaseOrder(order_number="PO-2026-0057",supplier_id=qualified.id,status="received",ordered_at=date(2026,7,22),required_date=date(2026,9,30)); session.add(corrective_po); await session.flush()
        corrective_line=PurchaseOrderLine(purchase_order_id=corrective_po.id,line_number=10,part_id=parts["MAG-ND-051"].id,quantity=Decimal("8"),received_quantity=Decimal("8"),unit_price=Decimal("648")); session.add(corrective_line); await session.flush()
        corrective_receipt=GoodsReceipt(receipt_number="GR-2026-0026",purchase_order_id=corrective_po.id,received_at=datetime(2026,8,5,10,tzinfo=timezone.utc),received_by=users["procurement@magnotherm.test"].id); session.add(corrective_receipt); await session.flush()
        session.add(ReceiptLot(receipt_id=corrective_receipt.id,po_line_id=corrective_line.id,supplier_id=qualified.id,part_id=corrective_line.part_id,internal_lot="MAG-L-2607",supplier_lot="AMS-2607-N48H",quantity=8,accepted_quantity=8,certificate_ref="CoC-AMS-2607; HcJ-2607"))
        session.add(StockPosition(part_id=corrective_line.part_id,warehouse="Main",on_hand=8,allocated=2,reorder_level=4))
        # Stock cover for the rest of the bought parts, so the procurement
        # screen shows a portfolio rather than the two magnet arrays alone.
        for part_number,on_hand,allocated,reorder in (("LFS-POR-010",64,16,40),("SEA-ORG-004",940,120,400),("CST-MCH-001",28,8,12),("CST-ADH-002",3,2,4),("FLD-WA-001",210,40,80),("PKG-CRT-001",6,4,10)):
            if part_number in parts: session.add(StockPosition(part_id=parts[part_number].id,warehouse="Main",on_hand=on_hand,allocated=allocated,reorder_level=reorder))

        # --- Customers -----------------------------------------------------
        # Three platforms at three stages, so the pipeline reads as a pipeline.
        session.add_all([
            Lead(name="Dr. Elena Fischer",company="Nordmarkt Retail",status="qualified"),
            Lead(name="Marco Bertani",company="Alpina Cold Chain",status="contacted"),
            Lead(name="Sofia Lindqvist",company="Nordic Data Halls AB",status="new"),
        ])
        opportunities=[
            Opportunity(title="Frankfurt low-GWP refrigeration pilot",customer_name="Nordmarkt Retail",stage="technical_validation",value=185000,expected_close=date(2026,11,30)),
            Opportunity(title="ECLIPSE rollout across twelve stores",customer_name="Nordmarkt Retail",stage="negotiation",value=1240000,expected_close=date(2027,3,31)),
            Opportunity(title="POLARIS 100 W laboratory cooling units",customer_name="Alpina Cold Chain",stage="qualification",value=64000,expected_close=date(2026,10,15)),
            Opportunity(title="STELLAR 125 kW data-hall feasibility",customer_name="Nordic Data Halls AB",stage="qualification",value=2100000,expected_close=date(2027,6,30)),
        ]
        frankfurt=CustomerSite(customer_name="Nordmarkt Retail",site_name="Frankfurt Pilot",address="Frankfurt am Main, DE")
        darmstadt_store=CustomerSite(customer_name="Nordmarkt Retail",site_name="Darmstadt Store 04",address="Darmstadt, DE")
        session.add_all([*opportunities,frankfurt,darmstadt_store]); await session.flush()
        # Both built units are placed: the returned one and the one still running.
        returned=DeployedUnit(unit_id=units["ECL-M-097"].id,customer_site_id=frankfurt.id,commissioned_at=date(2026,1,20),status="RMA")
        running=DeployedUnit(unit_id=units["ECL-M-104"].id,customer_site_id=darmstadt_store.id,commissioned_at=date(2026,3,2),status="operational")
        session.add_all([returned,running]); await session.flush()
        session.add_all([
            FieldEvent(deployed_unit_id=returned.id,occurred_at=datetime(2026,1,20,9,tzinfo=timezone.utc),event_type="commissioning",summary="Commissioned on the Frankfurt chilled aisle.",resolution="Accepted at 15.8 K span."),
            FieldEvent(deployed_unit_id=returned.id,occurred_at=datetime(2026,4,8,13,tzinfo=timezone.utc),event_type="failure",summary="Temperature span fell below 15 K after 400 h.",resolution="NCR and ECR opened; magnet lot quarantined."),
            FieldEvent(deployed_unit_id=returned.id,occurred_at=datetime(2026,4,22,10,tzinfo=timezone.utc),event_type="return",summary="Unit returned to Darmstadt for teardown."),
            FieldEvent(deployed_unit_id=running.id,occurred_at=datetime(2026,3,2,8,tzinfo=timezone.utc),event_type="commissioning",summary="Commissioned with the freeze-cast matrix.",resolution="Accepted at 16.1 K span."),
            FieldEvent(deployed_unit_id=running.id,occurred_at=datetime(2026,7,14,11,tzinfo=timezone.utc),event_type="service",summary="Six-month service: transfer fluid topped up, filters replaced.",resolution="No deviation found."),
        ])

        # --- Programmes ----------------------------------------------------
        # Two programmes: the scale-up that funds ECLIPSE, and HyLICAL, which is
        # the cryogenic hydrogen research line and sits several rungs lower.
        scaleup=Program(code="HZN-MAG-01",name="Industrial Magnetocaloric Scale-up",status="active")
        hylical=Program(code="HYLICAL",name="HyLICAL — cryogenic hydrogen liquefaction",status="active")
        session.add_all([scaleup,hylical]); await session.flush()
        wp=WorkPackage(program_id=scaleup.id,code="WP4",title="ECLIPSE field validation",budget=450000,trl_target=7)
        wp_manufacture=WorkPackage(program_id=scaleup.id,code="WP5",title="Pilot manufacturing line",budget=610000,trl_target=6)
        wp_cryo=WorkPackage(program_id=hylical.id,code="WP2",title="Cryogenic regenerator materials",budget=380000,trl_target=5)
        wp_demo=WorkPackage(program_id=hylical.id,code="WP3",title="Liquefaction demonstrator",budget=520000,trl_target=4)
        session.add_all([wp,wp_manufacture,wp_cryo,wp_demo]); await session.flush()
        session.add_all([
            TrlGate(work_package_id=wp.id,trl=5,status="approved",evidence="Validated in a representative retail cabinet."),
            TrlGate(work_package_id=wp.id,trl=6,status="approved",evidence="Pilot operated in relevant environment."),
            TrlGate(work_package_id=wp.id,trl=7,status="in_review",evidence="Corrective ECO pending field confirmation."),
            TrlGate(work_package_id=wp_manufacture.id,trl=5,status="approved",evidence="MBOM and routing released; first article built."),
            TrlGate(work_package_id=wp_manufacture.id,trl=6,status="planned",evidence="Requires a second build at rate."),
            TrlGate(work_package_id=wp_cryo.id,trl=3,status="approved",evidence="Gadolinium-alloy candidates characterised at 77 K."),
            TrlGate(work_package_id=wp_cryo.id,trl=4,status="in_review",evidence="Laboratory regenerator assembled; span measurement in progress."),
            TrlGate(work_package_id=wp_demo.id,trl=3,status="planned",evidence="Awaiting WP2 material selection."),
            ConsortiumPartner(program_id=scaleup.id,name="TU Darmstadt",role="Test and validation"),
            ConsortiumPartner(program_id=scaleup.id,name="Fraunhofer IPM (synthetic)",role="Magnet characterisation"),
            ConsortiumPartner(program_id=hylical.id,name="Clean Hydrogen Partnership",role="Funding authority"),
            ConsortiumPartner(program_id=hylical.id,name="University of Twente (synthetic)",role="Cryogenic modelling"),
            Deliverable(work_package_id=wp.id,code="D4.3",title="Field validation report",due_date=date(2026,12,15),status="in_progress"),
            Deliverable(work_package_id=wp_manufacture.id,code="D5.1",title="Pilot line process capability study",due_date=date(2027,2,28),status="planned"),
            Deliverable(work_package_id=wp_cryo.id,code="D2.2",title="Cryogenic material down-selection",due_date=date(2026,9,30),status="in_progress"),
            Deliverable(work_package_id=wp_demo.id,code="D3.1",title="Demonstrator design review pack",due_date=date(2027,1,31),status="planned"),
            Milestone(program_id=scaleup.id,name="CCB release of magnet corrective ECO",due_date=date(2026,9,30),status="at_risk"),
            Milestone(program_id=scaleup.id,name="Second pilot build at rate",due_date=date(2027,1,15),status="planned"),
            Milestone(program_id=hylical.id,name="TRL 4 gate review with the partnership",due_date=date(2026,11,20),status="planned"),
        ])

        # --- Lab assets ----------------------------------------------------
        # Deliberately spread across calibration states: one lapsed, one about
        # to lapse, three in date. A register where everything is valid teaches
        # the reader nothing about what the screen is for.
        assets=[
            (LabAsset(asset_tag="RIG-DA-02",name="1 kW AMR endurance rig",location="Darmstadt Lab",calibration_interval_days=180),"CAL-DA-2026-017",date(2026,4,1),date(2026,9,28),"pass"),
            (LabAsset(asset_tag="RIG-DA-01",name="100 W POLARIS bench rig",location="Darmstadt Lab",calibration_interval_days=365),"CAL-DA-2025-004",date(2025,6,12),date(2026,6,12),"pass"),
            (LabAsset(asset_tag="MET-TC-11",name="Thermocouple reference bath",location="Darmstadt Metrology",calibration_interval_days=365),"CAL-MET-2026-002",date(2026,2,10),date(2027,2,10),"pass"),
            (LabAsset(asset_tag="MET-DP-04",name="Differential pressure standard",location="Darmstadt Metrology",calibration_interval_days=180),"CAL-MET-2026-031",date(2026,3,3),date(2026,8,30),"pass"),
            (LabAsset(asset_tag="MAG-GS-02",name="Gaussmeter, transverse probe",location="Magnet Lab",calibration_interval_days=365),"CAL-MAG-2025-018",date(2025,9,1),date(2026,9,1),"pass"),
        ]
        first_asset=None
        for asset,certificate_number,calibrated,valid_until,result in assets:
            session.add(asset); await session.flush()
            first_asset=first_asset or asset
            session.add(CalibrationCertificate(asset_id=asset.id,certificate_number=certificate_number,calibrated_at=calibrated,valid_until=valid_until,result=result))
        assert first_asset is not None
        session.add_all([
            AssetBooking(asset_id=first_asset.id,starts_at=datetime(2026,8,12,8,tzinfo=timezone.utc),ends_at=datetime(2026,8,14,18,tzinfo=timezone.utc),booked_by=users["quality@magnotherm.test"].id,purpose="Corrective magnet endurance test"),
            AssetBooking(asset_id=first_asset.id,starts_at=datetime(2026,8,19,8,tzinfo=timezone.utc),ends_at=datetime(2026,8,20,18,tzinfo=timezone.utc),booked_by=users["engineer@magnotherm.test"].id,purpose="ECL-M-105 first-article acceptance"),
            AssetBooking(asset_id=assets[1][0].id,starts_at=datetime(2026,8,17,9,tzinfo=timezone.utc),ends_at=datetime(2026,8,18,17,tzinfo=timezone.utc),booked_by=users["engineer@magnotherm.test"].id,purpose="POLARIS regenerator screening"),
        ])

        # --- Resourcing ----------------------------------------------------
        # Four engineers across three weeks, one of them over capacity — the
        # case the screen exists to surface.
        loading=[
            ("engineer@magnotherm.test",wp,(36,38,30)),
            ("quality@magnotherm.test",wp,(24,32,28)),
            ("sysenq@magnotherm.test",wp_manufacture,(30,44,34)),
            ("manufacturing@magnotherm.test",wp_manufacture,(20,26,22)),
        ]
        for email,package,weekly in loading:
            person=users[email]
            for offset,hours in enumerate(weekly):
                week=date(2026,8,10)+timedelta(weeks=offset)
                session.add_all([
                    EngineerCapacity(user_id=person.id,week_start=week,available_hours=40),
                    ResourceAllocation(user_id=person.id,work_package_id=package.id,week_start=week,allocated_hours=hours),
                ])
        engineer=users["engineer@magnotherm.test"]
        session.add_all([
            TimesheetEntry(user_id=engineer.id,work_package_id=wp.id,work_date=date(2026,8,10),hours=7.5,description="ECR impact analysis"),
            TimesheetEntry(user_id=engineer.id,work_package_id=wp.id,work_date=date(2026,8,11),hours=8,description="MBOM re-derivation after the magnet change"),
            TimesheetEntry(user_id=users["quality@magnotherm.test"].id,work_package_id=wp.id,work_date=date(2026,8,11),hours=6,description="NCR-26-001 containment and lot trace"),
            TimesheetEntry(user_id=users["sysenq@magnotherm.test"].id,work_package_id=wp_manufacture.id,work_date=date(2026,8,12),hours=5.5,description="Routing review for the pilot line"),
        ])
        centre=CostCentre(code="ENG-ECL",name="ECLIPSE Engineering"); session.add(centre); await session.flush(); session.add_all([Budget(cost_centre_id=centre.id,work_package_id=wp.id,fiscal_year=2026,amount=450000),Commitment(cost_centre_id=centre.id,work_package_id=wp.id,reference="PO-2026-0042",amount=4920,source_amount=4920,source_currency="EUR"),Actual(cost_centre_id=centre.id,work_package_id=wp.id,reference="TS-2026-W33",amount=9800,source_amount=9800,source_currency="EUR"),WorkCentreRate(work_center="WC-COAT-01",hourly_rate=72),WorkCentreRate(work_center="WC-ASSY-02",hourly_rate=68),WorkCentreRate(work_center="WC-FILL-01",hourly_rate=66),WorkCentreRate(work_center="WC-TEST-01",hourly_rate=92)])
        await session.commit()
    from app.domains.ecm import service as ecm_service
    from app.domains.ecm.models import ChangeAction, EffectivityType
    from app.domains.ecm.release import release_change_order
    from app.domains.ecm.schemas import ChangeOrderLineIn
    async with session_factory() as session:
        systems=await _principal_for(session,"sysenq@magnotherm.test")
        order=await ecm_service.create_change_order(
            session,
            actor=systems,
            change_request_number=magnet_ecr,
            title="Release thermally stabilised N48H magnet array",
            disposition="Replace the field-failure magnet array and apply the new configuration from serial ECL-M-105.",
            effectivity_type=EffectivityType.SERIAL,
            effective_serial="ECL-M-105",
            lines=[ChangeOrderLineIn(action=ChangeAction.REPLACE_COMPONENT,parent_part_number="ECL-AMR-200",child_part_number="MAG-ND-050",new_child_part_number="MAG-ND-051",quantity=1,find_number="120",notes="N48H coercivity certificate and edge-temperature evidence required by incoming inspection.")],
        )
    async with session_factory() as session:
        systems=await _principal_for(session,"sysenq@magnotherm.test")
        released=await release_change_order(session,actor=systems,number=order.number)

    # Reassess after the release, not before it.
    #
    # The assessment attached when the ECR was raised could only report the
    # magnet's current standard cost — the corrective ECO had not captured its
    # baseline yet, so there were no two rollups to difference. Regenerating it
    # now gives the request the baseline-to-baseline cost delta the change
    # actually produced. `reassess` appends rather than overwrites, so the
    # version the board voted against survives alongside it.
    async with session_factory() as session:
        systems=await _principal_for(session,"sysenq@magnotherm.test")
        await ecm_service.reassess(session,actor=systems,number=magnet_ecr)
    async with session_factory() as session:
        await ingest(session,document_key="ECN-24-005",title="Freeze-cast matrix release",filename="ECN-24-005.md",content_type="text/markdown",data=b"# ECN-24-005\nReleased engineering change notice for ECLIPSE 1 kW. The lamellar freeze-cast LaFeSi matrix is effective from revision B. Public product context: ECLIPSE is a 1 kW refrigerant-free permanent-magnet cooling platform; its water-ethanol transfer medium flows over coated LaFeSi material.",acl_labels=["internal","engineering"],revision="A",user_id=None)
        notice=released.notice_number or "ECN-26-001"
        body=(f"# {notice}\n\nReleased corrective change for {magnet_ecr} and NCR-26-001. "
              "Supplier receipt GR-2026-0018 introduced magnet lot MAG-L-2312. "
              "As-built genealogy traced the lot to ECL-M-097, whose last two TP-ECL-1K readings failed the 15.0 K temperature-span limit. "
              f"Four CCB seats approved {magnet_ecr}; {order.number} replaced MAG-ND-050 with thermally stabilised MAG-ND-051 from serial ECL-M-105. "
              "The MBOM was re-derived and immutable before/after EUR cost rollups were captured. Incoming inspection requires lot-level coercivity and edge-temperature evidence.")
        await ingest(session,document_key=notice,title="Thermally stabilised magnet corrective release",filename=f"{notice}.md",content_type="text/markdown",data=body.encode("utf-8"),acl_labels=["internal","engineering","quality"],revision="A",user_id=None)
    logger.info("Seeded enterprise back-office, program, asset, resource and controlling data.")


async def _seed_governance() -> None:
    """Leave real agent proposals waiting, and record one evaluation run.

    The proposals are produced by calling the mutating tools through the tool
    registry as an agent, not by inserting rows. That matters: the previews a
    reviewer sees in the inbox are the genuine dry-run output of the same code
    path that would apply the change, so the screen cannot drift into showing
    something the approval would not actually do.
    """
    from app.core.principal import agent_principal
    from app.evals.models import EvalCaseResult, EvalRun
    from app.evals.runner import run_offline

    # Registration is an import side effect, so the registry is empty until the
    # loader runs. Without this the tools below simply do not exist and
    # `run_tool` reports an unknown tool.
    import app.tools.loader  # noqa: F401
    from app.tools.registry import run_tool

    session_factory = get_session_factory()

    # Two agents, two domains, two different approving roles — enough for the
    # inbox to show that authority travels with the operation.
    pending = [
        (
            "QMS Agent",
            "raise_non_conformance",
            {
                "title": "Transfer fluid below specified ethanol fraction",
                "description": (
                    "Incoming inspection of lot FLD-L-2608 measured an ethanol "
                    "fraction of 22.4% against the 24–26% specification. Two "
                    "drums are affected and have not yet been issued to a build."
                ),
                "source": "Incoming inspection",
                "severity": "Minor",
                "lot_number": "FLD-L-2608",
                "part_number": "FLD-WA-001",
            },
        ),
        (
            "ECM Impact Analyst",
            "raise_change_request",
            {
                "title": "Specify minimum ethanol fraction on the transfer fluid drawing",
                "problem_statement": (
                    "The transfer fluid is bought to a supplier specification "
                    "rather than a controlled drawing, so an out-of-band ethanol "
                    "fraction is only caught at incoming inspection."
                ),
                "proposed_solution": (
                    "Raise a controlled specification sheet for FLD-WA-001 with "
                    "the ethanol fraction as an inspected characteristic, and "
                    "reference it from the purchase order text."
                ),
                "affected_part_numbers": ["FLD-WA-001"],
                "origin": "Quality",
                "priority": "Normal",
            },
        ),
    ]

    filed = 0
    for agent_name, tool_name, arguments in pending:
        async with session_factory() as session:
            # `run_tool` reports a refusal as `{"error": …}` rather than
            # raising, so the model can correct itself. In a seed that means a
            # failure is silent unless the result is inspected — which is
            # exactly how this shipped empty the first time.
            result = await run_tool(
                session,
                tool_name,
                arguments,
                actor=agent_principal(agent_name),
            )
            if "error" in result:
                raise RuntimeError(f"Could not file {tool_name} proposal: {result['error']}")
            await session.commit()
            filed += 1

    async with session_factory() as session:
        cases = run_offline()
        run = EvalRun(
            suite="offline",
            status="passed" if all(case.passed for case in cases) else "failed",
            passed=sum(case.passed for case in cases),
            failed=sum(not case.passed for case in cases),
            metrics={"pass_rate": sum(case.passed for case in cases) / len(cases)},
        )
        session.add(run)
        await session.flush()
        for case in cases:
            session.add(
                EvalCaseResult(
                    run_id=run.id,
                    case_name=case.name,
                    category=case.category,
                    passed=case.passed,
                    score=case.score,
                    latency_ms=0,
                    detail=case.detail,
                    trajectory=[],
                )
            )
        await session.commit()

    logger.info("Seeded %d pending agent proposals and 1 evaluation run.", filed)


async def _seed_documents() -> None:
    """Create the controlled documents and check in their first revision."""
    from app.domains.pdm.documents import check_in, create_document

    session_factory = get_session_factory()
    for spec in DOCUMENTS:
        async with session_factory() as session:
            await create_document(
                session,
                actor=SYSTEM_PRINCIPAL,
                document_number=spec["document_number"],
                title=spec["title"],
                kind=spec["kind"],
                related_part_number=spec["related_part"],
            )
        async with session_factory() as session:
            await check_in(
                session,
                actor=SYSTEM_PRINCIPAL,
                document_number=spec["document_number"],
                filename=spec["filename"],
                data=spec["body"].encode("utf-8"),
                content_type=spec["content_type"],
                notes="Initial issue, seeded.",
            )
    logger.info("Checked in %d controlled documents.", len(DOCUMENTS))


async def _main() -> None:
    try:
        counts = await seed()
    finally:
        await dispose_engine()

    print("\nSeed complete:")
    for table, count in counts.items():
        print(f"  {table:<24} {count}")

    print(
        f"\n  Demo sign-in: any address below, password "
        f"{get_settings().demo_user_password!r}"
    )
    for spec in USERS:
        print(f"    {spec['email']:<34} {', '.join(spec['roles'])}")

    provider = get_embedding_provider()
    if not provider.is_semantic:
        print(
            "\n  NOTE: seeded with the deterministic embedding fallback. Knowledge\n"
            "  search will return results in a stable but ARBITRARY order, not a\n"
            "  semantic ranking. Set OPENAI_API_KEY in backend/.env and re-run\n"
            "  this script for real retrieval quality."
        )


if __name__ == "__main__":
    asyncio.run(_main())
