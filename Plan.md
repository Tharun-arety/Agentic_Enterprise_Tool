# Magnotherm Agentic Enterprise Toolchain — Build Plan

## Context

`A:\Fullstack projects\Magnotherm` currently holds a working vertical slice: a LangGraph
hub-and-spoke router over three read-only tools (BOM traversal, QMS metrics, pgvector
knowledge search), a FastAPI SSE chat endpoint, and a Next.js dashboard. It is roughly one
narrow domain of the nine the brief asks for, and every path is read-only and unauthenticated.

The goal is an internal tool suite for a magnetocaloric hardware company covering PDM/BOM and
engineering-change management, knowledge base, procurement and inventory, controlling and
budgeting, per-unit test and quality traceability, CRM, project and program tracking, asset and
lab management with calibration schedules, and time and resource planning — built as
open-source plus custom code, and operated by AI agents.

Decisions taken: **portfolio/showcase build** (synthetic data, must run locally and demo well),
**hybrid architecture** (custom engineering core + ERPNext for the back office), **depth-first on
engineering** (PDM → ECM → QMS traceability before the business domains), and **local users +
JWT roles** for identity.

The two reference documents supply the domain spine and are treated as requirements, not
background: DIN 199 EBOM/MBOM separation, ISO 10007 configuration management (identification,
change control, status accounting, audit), the ECR → CCB → ECO → ECN workflow, and VDI 2219
phased rollout.

## Guiding design decisions

**1. The engineering core is custom; the back office is adopted.** Nothing off-the-shelf models
LaFeSi lot traceability, magnetocaloric spec limits, or ISO 10007 configuration items well.
Conversely, re-implementing stock ledgers, purchase-order flows and double-entry budgeting is
unglamorous and already solved.

**2. ERPNext sits behind a port, not a hard dependency.** `domains/backoffice/ports.py` defines
one interface; `adapters/local.py` (Postgres tables, always available, seeded) and
`adapters/erpnext.py` (Frappe REST + webhooks, `--profile erpnext`) implement it. `/api/health`
reports which is live and the UI badges it — exactly the pattern
`app/embeddings.py` and `app/llm.py` already use for real-vs-fallback providers. The showcase
never fails to boot because a MariaDB container is unhappy, and the real integration is still
demonstrable.

**3. Agents propose; humans dispose.** Every mutating tool is declared `mutates=True` and cannot
execute directly. It produces an `AgentProposal` carrying a dry-run preview (a diff), which a
human approves in an inbox. This is what makes "operated by AI agents" safe enough to be
credible, and it is the same object that satisfies ISO 10007 status accounting.

**4. One tool implementation, two consumers — preserved.** The existing property that
`mcp_server.py` and the LangGraph nodes call the identical registry must survive the growth from
3 tools to ~40. The registry moves to `app/tools/registry.py` and each domain package registers
into it.

**5. Structured frames drive panels; prose is never parsed.** The existing `tool_result` /
`token` SSE split is correct and extends unchanged to every new domain.

## Phase 0 — Restructure and platform minimum

Depth-first was chosen over platform-first, so this phase is deliberately thin. It exists because
a CCB approval without an attributable actor is theatre, and Phase 2 needs one.

**Package restructure.** Flat `app/*.py` becomes:

```
backend/app/
  core/       config.py, db.py, security.py, audit.py, deps.py, llm.py, embeddings.py
  domains/    identity/ pdm/ ecm/ qms/ knowledge/ backoffice/ controlling/
              (each: models.py, schemas.py, service.py, router.py, tools.py)
  agents/     graph.py, prompts.py, spokes.py
  tools/      registry.py, mcp_server.py
  main.py
```

`app/models.py` splits into `domains/pdm/models.py` (Part, Assembly) and `domains/qms/models.py`
(LabTestRecord); `vector_models.py` → `domains/knowledge/models.py`. `db.py`, `config.py`,
`llm.py`, `embeddings.py` move to `core/` unchanged. Mechanical, and worth doing before nine
domains land in one 2000-line module.

**Alembic.** Replace `Base.metadata.create_all` as the schema path (keep it for the test/seed
fast path). `create_all` silently ignores column changes on existing tables, which will produce
confusing runtime errors halfway through this plan.

**Identity** — `domains/identity/`: `User` (email, full_name, password_hash via
`passlib[argon2]`, roles, is_active), roles as an enum (`ENGINEER`, `CCB_MEMBER`, `QUALITY`,
`MANUFACTURING`, `PROCUREMENT`, `CONTROLLER`, `ADMIN`), `POST /api/auth/login` issuing a JWT with
a roles claim, and a `require_roles(...)` FastAPI dependency in `core/deps.py`. Seed five demo
users, one per role, so the CCB quorum is demonstrable.

**Audit** — `core/audit.py` + `AuditEvent` (append-only): occurred_at, actor_type
(`human`|`agent`), actor_id, agent_name, action, entity_type, entity_id, `before`/`after` JSONB,
reason, correlation_id. Every service-layer mutation writes one inside the same transaction.

**Agent write spine** — `AgentProposal`: proposed_by_agent, tool_name, arguments JSONB, preview
JSONB, status (`pending`/`approved`/`rejected`/`applied`/`failed`), reviewed_by, applied_at,
result. Plus `POST /api/proposals/{id}/approve|reject` gated on roles.

**Infra** — `docker-compose.yml`: `pgvector/pgvector` Postgres, MinIO, backend, frontend, and an
`erpnext` profile (off by default). MinIO is reached through a `FileStore` port with a
local-filesystem fallback, same idiom as the adapters.

## Phase 1 — PDM depth

**Part master.** Extend `Part` with `lifecycle_state` (`IN_DESIGN`/`PROTOTYPE`/`RELEASED`/
`OBSOLETE`), `part_class` (`MECHANICAL`/`ELECTRICAL`/`SOFTWARE`/`RAW_MATERIAL`/`CONSUMABLE`/
`PACKAGING`/`PHANTOM`/`ASSEMBLY`/`DOCUMENT`), `uom`, `make_or_buy`, `standard_cost` + `currency`,
`is_configuration_item` + `ci_criticality` (ISO 10007 configuration identification), and
compliance attributes `pfas_free`, `gwp_direct`, `rohs_reach_status`,
`contains_heavy_rare_earth`. Those last four let an agent answer "prove POLARIS is PFAS-free" by
walking the BOM and citing components — the ideation document names the EBOM as the vehicle for
exactly that claim.

**`PartRevision` as a first-class row** (replacing the `revision` string column): part_id,
revision, lifecycle_state, released_at, released_by, superseded_by, `eco_id`, change_summary.
Required before anything can answer "which revision was in unit ECL-M-104".

**BOM view separation (DIN 199).** `Assembly` becomes `BomEdge`, keeping the edge-table shape
(the existing rationale in `models.py:122` is right and stays). Added: `bom_type`
(`EBOM`|`MBOM`, extensible), `parent_revision_id`/`child_revision_id` so edges bind revisions
rather than bare parts, `effectivity_from`/`effectivity_to` and `effective_from_serial`,
`eco_in`/`eco_out` FKs, `find_number`, `reference_designator`, and MBOM-only `operation_seq`,
`is_phantom`, `scrap_factor`.

**MBOM derivation as an explicit, diffable object.** `derive_mbom()` copies the released EBOM and
applies stored `MbomDelta` rows — added consumables (the water/ethanol charge volume), packaging,
phantom sub-kits, routing assignment. Storing deltas rather than a detached copy means the
EBOM↔MBOM gap is inspectable and re-derivable after an engineering change. The reference document
calls this handoff the most critical in hardware manufacturing; making it a first-class object is
the strongest single feature in this build. Paired with `Operation` rows (op_seq, work_center,
setup/run time, work-instruction document ref — e.g. the anti-corrosion coating cure profile).

**Queries.** Extend the existing recursive CTE in `mcp_tools.py:61` with a `bom_type` filter, an
effectivity-date filter, and `extended_quantity` rollup (parent × child). Add a **where-used**
reverse CTE — this is the engine of ECO impact analysis and Phase 2 depends on it. Both keep the
path-array cycle guard already in place.

**Baselines and diff.** `ConfigurationBaseline`: a named, frozen snapshot of a product's full BOM
at a point in time, tied to a platform (POLARIS / ECLIPSE / STELLAR / HYLICAL). Plus
`diff_baselines(a, b)` returning added/removed/changed rows — the colour-coded BOM revision diff
the document praises in Duro, and a strong demo surface.

**File vault.** `Document` + `DocumentRevision` (CAD, drawings, work instructions, test reports),
content-hashed, stored through the `FileStore` port, with `locked_by` check-in/check-out and
links to parts, revisions and ECOs.

Files: `domains/pdm/{models,schemas,service,router,tools}.py`, `domains/pdm/queries.py` (the
CTEs).

## Phase 2 — Engineering Change Management

The document's four-phase workflow, implemented as an explicit table-driven state machine with
guards in `domains/ecm/service.py` — invalid transitions rejected at the service layer, not by
convention.

- **`ChangeRequest` (ECR)** — number `ECR-YY-NNN`, problem_statement, proposed_solution,
  originator, origin (`RND`/`SUPPLY_CHAIN`/`QUALITY`/`FIELD`/`COST`), priority, affected
  configuration items, preliminary technical/cost/schedule impact, status.
- **`ImpactAssessment`** — generated, not typed. Walks where-used to find every affected assembly
  and product; finds the `TestProtocol`s and historical `LabTestRecord`s bound to the affected CI
  that require re-validation (the document's explicit requirement); queries the back-office port
  for open POs and on-hand stock of the affected item; computes the cost delta from the rollup.
  This is the flagship agent capability.
- **`ChangeBoardReview` / `Approval`** — per-member decision (`approve`/`reject`/`abstain`/
  `request_info`), comment, decided_at, actor from the JWT. Quorum configured per role: Systems
  Engineering, Quality, Manufacturing, Procurement.
- **`ChangeOrder` (ECO)** — disposition, effectivity (`ASAP` | date | serial-break), the revisions
  it creates, implementation tasks.
- **`ChangeNotice` (ECN)** — broadcast record, recipients including external partners, issued_at,
  acknowledgements.

**`release_eco()`** is one transactional service call: bump part revisions, close superseded edge
effectivity, open new edges, snapshot a new `ConfigurationBaseline`, push the MBOM through the
back-office port, emit the ECN, write audit events.

**Closed loop to the knowledge base**: released ECO and ECN text is auto-embedded into
`KnowledgeEmbedding`, so the RAG corpus self-populates from transactional data instead of being a
hand-seeded fixture.

## Phase 3 — QMS and per-unit traceability

- **`Unit`** — serial_number as a first-class entity: part_revision built to,
  `as_built_baseline_id`, built_at, plant, status (`IN_PRODUCTION`/`IN_TEST`/`SHIPPED`/`FIELD`/
  `RMA`/`SCRAPPED`), customer_ref.
- **`UnitComponent`** — the as-built genealogy, the "digital birth certificate": unit_id,
  part_revision_id, quantity, **lot/batch number**, supplier_lot, child serial where serialised,
  installed_at, operation_seq. LaFeSi alloy batch traceability is a named requirement.
- **`TestProtocol`** — versioned protocol carrying spec limits (min/max/target) per metric, so
  pass/fail is computed rather than asserted, and so an ECO can name which protocols need re-running.
- **`LabTestRecord`** — extend the existing model with `unit_id`, `test_protocol_id`,
  `equipment_id`, `operator_id`, and computed pass/fail against the protocol. Metric-name casing
  (`temperature_span_delta_K`) stays as-is; the rationale in `models.py:1` holds.
- **`NonConformance` (NCR)** + **`CapaAction`** — raised against a unit, part or lot; disposition
  (`use_as_is`/`rework`/`scrap`/`return`); escalates into an ECR when a design change is needed,
  closing the QMS → ECM loop.

Two CTEs give forward and backward traceability: "what is inside ECL-M-104" and "which units
contain LaFeSi lot L-2405". A test record whose equipment was out of calibration at
`recorded_at` is flagged invalid — enforced, not advisory (depends on Phase 5 assets).

## Phase 4 — Back-office port and ERPNext

`domains/backoffice/ports.py` — one interface over Item, Supplier, PurchaseOrder + lines, Stock,
SerialNo, Customer/Lead/Opportunity, Project/Task, Timesheet, Asset + MaintenanceSchedule,
CostCenter/Budget/Expense.

- `adapters/local.py` — Postgres tables, always available, seeded with synthetic data. The
  showcase default.
- `adapters/erpnext.py` — Frappe REST (`/api/resource/<Doctype>`), token auth, webhook receiver
  for inbound changes. `docker compose --profile erpnext up` brings up ERPNext + MariaDB + Redis.
- Sync is idempotent and keyed by `external_ref` columns on our entities: part master → Item,
  released MBOM → BOM, `Unit.serial_number` → Serial No.
- `/api/health` gains `backoffice_adapter` and `backoffice_live`; the header badges it alongside
  the existing stub-model and non-semantic-search warnings.

## Phase 5 — Remaining business domains

Delivered through the port, with thin custom tables only where the domain demands specificity:

- **Procurement & inventory** — POs, goods receipt capturing lot numbers (which feed
  `UnitComponent`), reorder points, supplier lead times, long-lead flags for NdFeB arrays and
  superconducting magnets.
- **CRM** — leads/opportunities per platform; a customer account links to the deployed `Unit`
  serials at that site, so an account view reaches through to real field test data.
- **Projects & programs** — HyLICAL modelled as a program with TRL gates (TRL 3 → TRL 5), work
  packages, EU/Clean Hydrogen Partnership deliverables, consortium partners. Milestones link to
  ECOs and baselines.
- **Assets & lab management** — equipment register, calibration interval / last-calibrated /
  next-due with certificate documents, and test-rig booking. Out-of-calibration equipment
  invalidates test records per Phase 3.
- **Time & resource planning** — timesheets against work packages, engineer capacity vs.
  allocation, rig booking conflicts.

## Phase 6 — Controlling and budgeting

Cost rollup as a recursive CTE over the MBOM × `standard_cost` plus operation labour rates,
producing per-unit product cost against a per-platform target. `Budget` per cost centre/project/
period, `Commitment` (open POs) and `Actual` (invoices, timesheets); variance = budget −
committed − actual. ECO cost impact is the rollup delta between two baselines, which is what
wires controlling into the CCB decision.

## Phase 7 — The agent fleet

**Two-level routing.** The current single router with exactly one tool per spoke does not scale
to nine domains. It becomes: domain router → domain agent holding a *scoped toolset*. The
principle that made the original design good — a node can only see its own domain's tools — is
preserved; only the cardinality changes.

Agents: Router · PDM · **ECM Impact Analyst** · QMS/Traceability · Knowledge · Procurement ·
Controlling · Program · **Compliance** (traces PFAS/GWP/RoHS claims to components, prepares
PCA/FCA configuration audits) · Synthesizer.

**Write tools** are declared `mutates=True` in the registry and route through the Phase 0
proposal spine. The agent answers "I have prepared ECO-24-011 for your approval" and the diff
renders in the approval inbox.

**Scheduled agents** (cron), each producing a proposal or a notification and never a silent
write: calibration due within 30 days; ECRs stalled in CCB beyond N days; long-lead stock below
reorder; budget variance over threshold; out-of-spec test records; ECO effectivity dates
arriving.

**Evals** — `backend/evals/`: golden questions per domain with expected tool calls and result
assertions, runnable offline against the stub client, extending `scripts/verify.py`.

## Frontend

Section switching moves from `useState` in `DashboardShell.tsx:57` to real App Router routes
(`/pdm`, `/ecm`, `/qms`, `/procurement`, …) so views are linkable; `AppSidebar.tsx` grows to
grouped nav (Engineering / Quality / Operations / Business / Agents). The chat sidebar stays
global and its `tool_result` handling generalises so any domain payload drives its matching panel.

New views: part master + revision history; BOM tree with EBOM/MBOM toggle and colour-coded
revision diff; ECR/ECO board with the CCB approval panel; unit genealogy tree; NCR list;
procurement and stock; calibration calendar; program/TRL timeline; budget variance; and the
**agent approval inbox**, which is where a reviewer sees a proposed diff and accepts or rejects it.

`frontend/lib/types.ts` continues to mirror `schemas.py` by hand, per the note at `schemas.py:1`.

Note for whoever implements: `frontend/AGENTS.md` warns that this Next.js version differs from
training data — read `node_modules/next/dist/docs/` before writing App Router code. Also
`frontend/.git` still exists from `create-next-app` and must be removed before the tree can be a
single repository.

## Repository as its own exhibit

Since this is a showcase of an agent-built system, commit the agentic development setup:
`.claude/CLAUDE.md` with the architecture invariants above, per-domain skills, and subagent
definitions. The repo then documents how it was built, not just what it does.

## Verification

Each phase ships with its checks; nothing is called done on inspection alone.

1. `python -m scripts.seed` — extended per phase; timestamps stay hard-coded constants so
   re-seeding is byte-identical and the charts render the same shape (existing property, preserve it).
2. `python -m scripts.verify` — extended per phase: assert row counts, exercise every new tool
   directly, and run full graph turns against the real database with the stub client.
3. `pytest` for service-layer logic that is genuinely hard to eyeball: the ECM state machine's
   illegal transitions, effectivity-date filtering on BOM queries, MBOM re-derivation after an
   EBOM change, cost rollup arithmetic, and the where-used CTE against a part shared by two parents.
4. `python -m backend.evals.run` — golden agent questions per domain, offline.
5. End-to-end per phase, with the servers up (`uvicorn app.main:app --reload --port 8000`,
   `npm run dev -- --port 3001`), driven through the browser preview tools: log in as an engineer,
   raise an ECR, log in as each CCB role and approve, release the ECO, confirm the BOM diff and the
   new baseline, then confirm the ECN text became searchable in the knowledge panel.
6. `docker compose up` from clean, and separately `--profile erpnext`, confirming `/api/health`
   reports the correct adapter and the UI badge matches.
7. `npm run typecheck && npm run lint` in `frontend/`.

## Sequencing note

Phases 0–3 are the engineering core and the substance of the depth-first choice; they are worth
completing properly before Phase 4 opens the back-office seam. Phases 5–7 are broad but shallow by
comparison, since the port and the agent spine already exist by then.