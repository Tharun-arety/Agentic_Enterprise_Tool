# Magnotherm — Agentic ERP / PDM / QMS Toolchain

Engineering data access for refrigerant-free magnetocaloric cooling systems,
behind a single agentic interface.

PDM, ECM, QMS, procurement, CRM, programs, lab assets, resources, controlling,
and controlled engineering knowledge are unified behind a two-level LangGraph.
The router selects up to three domain agents, each receives only its registered
tools, and the synthesizer receives bounded structured evidence with citations.

Reads are answered directly. **Writes are not**: a mutating tool computes what
would change, files it as a proposal, and waits for a person holding the right
role to approve it. Nothing an agent does takes effect on its own authority.

```
                          ┌──────────────┐
                          │    Router    │   intent classification (hub)
                          └──────┬───────┘
             ┌───────────┬───────┴───────┬────────────┐
             ▼           ▼               ▼            │ general
      ┌────────────┐ ┌────────────┐ ┌──────────────┐  │
      │ PDM Agent  │ │ QMS Agent  │ │  Knowledge   │  │
      │    BOM     │ │  metrics   │ │  pgvector    │  │
      └──────┬─────┘ └─────┬──────┘ └──────┬───────┘  │
             └─────────────┴───────────────┴──────────┘
                             ▼
                      ┌──────────────┐
                      │ Synthesizer  │   streams the answer
                      └──────────────┘
```

## Stack

| Layer | Choice |
|---|---|
| Backend | FastAPI, SQLAlchemy 2 (async) over asyncpg |
| Database | PostgreSQL + `pgvector` (Neon), Alembic migrations |
| Identity | Local users, Argon2id hashes, JWT with a roles claim |
| Document vault | Local filesystem by default; S3/MinIO behind the same port |
| Orchestration | LangGraph — graph only; the official `openai` SDK makes every model call |
| Tools | Exposed both in-process to the graph and over MCP stdio |
| Frontend | Next.js 16 (App Router), React 19, Tailwind v4, Recharts, Lucide |

## Prerequisites

- Python 3.11+
- Node.js 20+
- A PostgreSQL database with the `vector` extension available. Neon supports it
  natively; nothing needs installing locally.

## Setup

### 1. Backend

```bash
cd backend
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
copy .env.example .env
```

Edit `backend/.env` and set `DATABASE_URL` to your Neon connection string.
Paste it exactly as Neon gives it to you — `app/db.py` rewrites the scheme to
`postgresql+asyncpg://`, strips libpq-only parameters such as `?sslmode=require`
and `?channel_binding=require` that asyncpg cannot accept, and re-applies TLS
through `connect_args`.

Both Neon endpoints work. The **pooled** (`-pooler`) host runs PgBouncer in
transaction mode, which cannot hold the session state asyncpg's prepared
statements need; `db.py` disables both statement caches
(`statement_cache_size=0` on asyncpg, `prepared_statement_cache_size=0` on the
SQLAlchemy dialect) so it connects cleanly. Verified against PostgreSQL 18.4 with
pgvector 0.8.1 on a pooled endpoint.

`OPENAI_API_KEY` is **optional at this stage** — see [Running without an API
key](#running-without-an-api-key).

### 2. Apply the schema

```bash
cd backend
.venv\Scripts\python.exe -m alembic upgrade head
```

`migrations/env.py` reads `DATABASE_URL` from `.env` and normalises it the same
way the app does, so a Neon connection string that works for `uvicorn` works
here. It also creates the `vector` extension before the first migration runs.

To verify the whole chain from nothing, point it at a scratch database on the
same local PostgreSQL the test suite uses:

```bash
python -c "import pgserver,pathlib;print(pgserver.get_server(pathlib.Path('var/testdb').resolve(),cleanup_mode=None).get_uri())"
```

then create a database on that server and run `DATABASE_URL=<uri>/scratch
alembic upgrade head`, `alembic check`, `alembic downgrade base`. The current
chain builds all three revisions from empty with no drift and reverses cleanly,
leaving only Alembic's own `alembic_version` table.

There is deliberately no "run the migrations against a throwaway *schema*"
switch. `schema_translate_map` only rewrites SQLAlchemy-constructed clauses, so
`op.create_table` would honour it while `op.add_column`, `op.alter_column` and
raw `op.execute` would not — such a run writes half to the scratch schema and
half to the real one, and only says so if it happens to fail. A separate
database has no such split.

The seed script calls `create_all` directly, so `alembic upgrade head` is not
strictly required to get running. It is required to keep an existing database
in step once the schema changes: `create_all` adds missing tables but silently
ignores changed columns.

### 3. Seed the replica dataset

```bash
cd backend
.venv\Scripts\python.exe -m scripts.seed
```

This creates the schema, installs the `vector` extension, and writes:

- **7 users**, one per role, so the four-seat Change Control Board is
  demonstrable. All share `DEMO_USER_PASSWORD` (default `magnotherm`):

  | Address | Roles |
  |---|---|
  | `admin@magnotherm.test` | admin |
  | `sysenq@magnotherm.test` | engineer, systems_engineering |
  | `quality@magnotherm.test` | quality |
  | `manufacturing@magnotherm.test` | manufacturing |
  | `procurement@magnotherm.test` | procurement |
  | `controlling@magnotherm.test` | controller |
  | `engineer@magnotherm.test` | engineer |

- **12 parts, 13 revisions, 14 retained EBOM edges** — the ECLIPSE 1kW tree and its effective revision history:

  ```
  ECL-SYS-1000  ECLIPSE 1kW Retail Chiller                        rev C
  ├─ ECL-AMR-200  Active Magnetic Regenerator Module              rev B
  │  ├─ LFS-POR-009  LaFeSi Matrix, epoxy-bonded  ×6   until 2025-06-01
  │  ├─ LFS-POR-010  LaFeSi Matrix, freeze-cast   ×8    from 2025-06-01
  │  ├─ MAG-ND-050   Neodymium Permanent Magnet Array (rotational)
  │  ├─ CST-MCH-001  3D Printed Double Corrugated Housing ×2
  │  └─ SEA-ORG-004  O-ring seal ×4
  └─ HYD-PMP-100  Low-Pressure Hydraulic Loop                     rev A
     ├─ FLD-WA-001  Water/Alcohol Transfer Medium (< 1 bar)
     └─ SEA-ORG-004  O-ring seal ×2
  ```

  Three details there are load-bearing rather than decorative:

  - **The two LaFeSi matrices are one change, phased by date.** That is ECO-24-005.
    Exploding the product at 2025-05-01 returns the epoxy-bonded bed at ×6;
    today it returns the freeze-cast one at ×8. Units built before the change
    keep resolving to what they actually contain.
  - **The O-ring sits under two parents**, which is why structure lives in an
    edge table. Where-used finds both, and names the product above them once.
  - **The O-ring has no PFAS declaration.** The compliance rollup for the
    ECLIPSE therefore comes back *unproven* and names it — the answer an
    evidence-based claim has to give when a supplier has not replied.

- **An MBOM derived from that EBOM**, not hand-built: engineering lines copied,
  then 5 manufacturing deltas replayed — the 1.8 L fill volume, the assembly
  adhesive, the export crate, the pump loop as a phantom kit, and a 5% scrap
  allowance on the end-cap O-rings — plus a 4-step routing.
- **Two configuration baselines**, captured either side of the geometry change,
  so `diff_baselines` has something real to compare.
- **Two controlled documents** with real content, checked in through the vault.
- **Two governed change requests.** `ECR-26-001` remains part-way through the
  Change Control Board for the O-ring declaration, with two of four seats voted.
  `ECR-26-002` is the completed operational thread: failed magnet lot
  `MAG-L-2312` → `NCR-26-001` → four-seat CCB approval → `ECO-26-001` → released
  `ECN-26-001`, replacement part `MAG-ND-051`, revised MBOM, and before/after
  immutable cost snapshots.
- **Two built units with real genealogy.** `ECL-M-097` was built in March 2025
  and `ECL-M-104` in February 2026 — either side of the freeze-cast change — so
  their build records genuinely differ: one contains the epoxy-bonded matrix ×6,
  the other the freeze-cast one ×8. Each component carries the material lot it
  came from, and both records include the adhesive that exists only on the MBOM.

- **Acceptance limits, and a unit that fails them.** Protocol `TP-ECL-1K rev A`
  puts a 15.0 K floor under the temperature span. `ECL-M-104` passes all five
  readings; `ECL-M-097` is the unit TF-24-018 describes — it degrades over five
  readings and the last two are stored as failures naming the metric and the
  limit they broke.

- **A non-conformance scoped to a material lot.** `NCR-26-001` is raised against
  magnet lot `MAG-L-2312`, not against the unit that failed, and the affected
  units are resolved from the build records rather than typed in.
- **5 knowledge documents**, including ECO-24-005 on the move from epoxy-bonded
  AMR geometries to freeze-cast lamellar channels and the exact controlled
  `ECN-26-001` revision A release evidence.

The product baseline is grounded in Magnotherm's public ECLIPSE and technology
information. Magnotherm's private ERP, QMS, supplier, unit, cost, and approval
records are not public; all transactional organizations, purchase orders,
receipts, lots, serial numbers, costs, failures, votes, and controlled documents
in this portfolio are therefore realistic synthetic data. They are inserted via
the same domain services used by the APIs—not hard-coded dashboard fixtures—so
traceability, effectivity, cost, permissions, and retrieval behave like a working
enterprise system.

Seeded timestamps are hard-coded constants, so re-running produces byte-identical
data and the chart renders the same shape every time.

### 4. Verify

```bash
cd backend
.venv\Scripts\python.exe -m scripts.verify
```

Checks connectivity and the `vector` extension, asserts the seeded row counts,
exercises all three tools directly, and runs full graph turns against the real
database using a stub model client.

Then the unit suite, which covers the parts that are hard to eyeball —
password and token handling, the login path, and the propose/approve/apply
lifecycle:

```bash
cd backend
.venv\Scripts\python.exe -m pytest
```

**No setup required.** The suite starts its own PostgreSQL, in-process, from the
`pgserver` wheel — which bundles the server binaries *and* pgvector 0.6.2. No
database, no container, no daemon. The cluster lives in `backend/var/testdb`
(gitignored, ~55 MB) and is kept between runs, so after the first `initdb` the
server starts in about 20 ms and stops when pytest exits.

That default is about speed, not convenience. The schema needs a real Postgres —
it depends on `pgvector`, `ARRAY` and `JSONB`, and swapping in SQLite would mean
testing a different schema than the one that ships. But the tests compute almost
nothing; they are a few thousand tiny queries, and against a hosted database
each one costs a network round trip:

| Where the suite runs | Per round trip | 92 tests |
|---|---|---|
| Local `pgserver` | 0.6 ms | **40 s** |
| Neon (`TEST_DATABASE_URL` set) | ~375 ms | ~17 min |

Set `TEST_DATABASE_URL` to run against a remote database anyway. Either way the
suite isolates itself by building a `mt_test` schema, pointing `search_path` at
it, and dropping it afterwards, so pointing it at the same database as the app
is safe.

Two things about that isolation are worth knowing before changing it, because
both failure modes are silent:

- It must be `search_path`, not SQLAlchemy's `schema_translate_map`. The map
  only rewrites SQLAlchemy-constructed clauses, so ORM queries would land in
  `mt_test` while the hand-written recursive CTEs kept reading `public`.
- The path is set with `SET` on every pool checkout, against Neon's **direct**
  endpoint (derived automatically from your URL). Neon's proxy silently drops
  `search_path` as a startup parameter, and PgBouncer's transaction mode would
  not carry it between transactions anyway.

The fixture checks the outcome rather than trusting either: if the tables do not
land in `mt_test` and unqualified names do not resolve there, it raises instead
of running against what is probably your application data.

### 5. Run

```bash
# Terminal 1 — API on :8000
cd backend
.venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8000

# Terminal 2 — UI on :3001
cd frontend
npm run dev -- --port 3001
```

Open <http://localhost:3001>.

## Running without an API key

The stack is deliberately usable before `OPENAI_API_KEY` is set, so everything
except the language model itself can be built and verified first:

| Component | Without a key |
|---|---|
| Schema, seeding, BOM and QMS tools | Fully functional |
| REST endpoints and the whole dashboard | Fully functional |
| Vector search | Runs, but on a **deterministic fallback** embedding provider |
| `/api/chat` | Runs, but answers come from a **stub model client** |

Two honest caveats, surfaced in the UI as warning badges and in the server log at
boot rather than hidden:

- **The fallback embeddings are not semantically meaningful.** They are stable,
  unit-norm vectors derived from a hash of the text, so cosine distances are
  arithmetically valid and repeatable but carry no meaning. Knowledge search
  returns results in a consistent yet **arbitrary** order.
- **The stub model client returns canned text.** The graph, the tools, the
  streaming, and the frontend are all real; only the model is not.

Set `OPENAI_API_KEY` in `backend/.env` and **re-run the seed script** (the stored
vectors must be regenerated with the real provider), then restart the API.

## Configuration

All configuration lives in `backend/.env`; see `backend/.env.example`.

| Variable | Default | Notes |
|---|---|---|
| `DATABASE_URL` | — | Required. Neon connection string. |
| `JWT_SECRET` | *(dev value)* | Public until set. See Known limitations. |
| `JWT_EXPIRY_MINUTES` | `720` | A working day without a re-login. |
| `DEMO_USER_PASSWORD` | `magnotherm` | Shared by every seeded account. |
| `TEST_DATABASE_URL` | *(empty)* | Falls back to `DATABASE_URL`; the suite builds its own schema. |
| `OPENAI_API_KEY` | *(empty)* | Optional; enables live answers and semantic search. |
| `OPENAI_MODEL` | `gpt-4o-mini` | Router + all three retrieval spokes. |
| `OPENAI_SYNTHESIS_MODEL` | *(empty)* | Final answer only; falls back to `OPENAI_MODEL`. |
| `OPENAI_EMBEDDING_MODEL` | `text-embedding-3-small` | 1536-dim. |
| `AGENT_MAX_TOOL_ITERATIONS` | `4` | Ceiling on each spoke's tool loop. |
| `FRONTEND_ORIGIN` | `http://localhost:3001,http://localhost:3000` | Comma-separated CORS allow-list. Must include the UI's actual port. |

**No model identifier is hard-coded anywhere in the Python.** Swapping models is
a one-line `.env` change.

Cost note: the router fires on every message and each spoke makes 2+ calls per
turn, so the retrieval path dominates request count. Keeping it on the mini tier
is what makes this cheap; `OPENAI_SYNTHESIS_MODEL` exists so you can upgrade the
one-call-per-turn synthesis step without paying for it on the high-volume path.
Per-node token usage is logged.

## MCP server

The same three tools are exposed over MCP stdio for any MCP client:

```bash
cd backend
.venv\Scripts\python.exe -m app.tools.mcp_server
```

The tool bodies are thin wrappers over the same registry the LangGraph nodes
call, so the MCP surface and the in-process surface cannot diverge.

## API

| Method | Path | Auth | Purpose |
|---|---|---|---|
| `GET` | `/api/health` | — | Status, plus which providers are live vs. fallback |
| `POST` | `/api/auth/login` | — | Exchange credentials for a JWT |
| `GET` | `/api/auth/me` | token | Resolve the token against the live user record |
| `GET` | `/api/parts/{part_number}` | — | Part master + revision history |
| `GET` | `/api/parts/{part_number}/bom` | — | Nested BOM tree (`?bom_type=`, `?as_of=`) |
| `GET` | `/api/parts/{part_number}/where-used` | — | Every assembly containing the part |
| `GET` | `/api/parts/{part_number}/compliance` | — | PFAS / HREE / RoHS / GWP rollup |
| `GET` | `/api/baselines` | — | Captured configuration baselines |
| `GET` | `/api/baselines/diff` | — | What changed between two of them |
| `GET` | `/api/documents` | — | Controlled documents and their revisions |
| `POST` | `/api/documents/{n}/checkout` | token | Claim the next revision |
| `GET` | `/api/documents/{n}/content` | — | Download, hash-verified on the way out |
| `GET` | `/api/ecm/requests` | — | Change requests, newest first |
| `GET` | `/api/ecm/requests/{n}` | — | One ECR with its votes, quorum and impact |
| `POST` | `/api/ecm/requests` | engineer | Raise an ECR |
| `POST` | `/api/ecm/requests/{n}/submit` | engineer | Send it to the board |
| `POST` | `/api/ecm/requests/{n}/review` | CCB seat | Cast one seat's vote |
| `POST` | `/api/ecm/requests/{n}/reassess` | token | Recompute the impact |
| `POST` | `/api/ecm/orders` | sys. eng. | Author the ECO for an approved ECR |
| `GET` | `/api/ecm/orders/{n}` | — | One ECO with its lines and notices |
| `POST` | `/api/ecm/orders/{n}/release` | sys. eng. | Release it — see below |
| `GET` | `/api/qms/{serial_number}` | — | Metrics, limits and pass/fail per reading |
| `GET` | `/api/units/{serial}/genealogy` | — | What that article was actually built from |
| `GET` | `/api/lots/{lot}/trace` | — | Every unit containing a lot of material |
| `GET` | `/api/ncrs` | — | Non-conformance reports |
| `POST` | `/api/ncrs` | quality | Raise one against a unit, part or lot |
| `POST` | `/api/ncrs/{n}/disposition` | quality | Use as is / rework / scrap / return |
| `POST` | `/api/ncrs/{n}/escalate` | quality | Open an ECR carrying its evidence |
| `POST` | `/api/ncrs/{n}/close` | quality | Close, once actions are complete |
| `GET` | `/api/knowledge?q=&limit=` | — | Vector search |
| `POST` | `/api/chat` | — | Agent turn, streamed as SSE |
| `GET` | `/api/proposals` | token | The approval inbox |
| `GET` | `/api/proposals/{id}` | token | One proposal with its diff |
| `POST` | `/api/proposals/{id}/approve` | role | Approve and apply |
| `POST` | `/api/proposals/{id}/reject` | role | Reject, leaving the data alone |
| `GET` | `/api/audit` | token | Configuration status accounting |

"role" means the specific role named on that proposal, which comes from the tool
that produced it. Authority travels with the operation rather than being
restated on every route.

`/api/chat` frames: `agent_state`, `tool_result`, `token`, `final`, `error`. The
structured `tool_result` payload drives the BOM tree and the chart; `token`
drives the chat bubble. **The UI never parses prose to find data.**

## Project layout

```
Magnotherm/
├─ backend/
│  ├─ app/
│  │  ├─ core/             cross-cutting infrastructure
│  │  │  ├─ config.py      typed settings
│  │  │  ├─ db.py          async engine, Neon URL normalisation, schema bootstrap
│  │  │  ├─ embeddings.py  OpenAI + deterministic fallback providers
│  │  │  ├─ llm.py         OpenAI + stub model clients
│  │  │  ├─ security.py    Argon2id hashing, JWT issue/verify
│  │  │  ├─ principal.py   one "who is acting" type for humans and agents
│  │  │  ├─ deps.py        session + current principal + require_roles()
│  │  │  ├─ audit.py       append-only AuditEvent
│  │  │  ├─ proposals.py   the agent write path (propose -> approve -> apply)
│  │  │  └─ router.py      approval inbox + audit endpoints
│  │  ├─ domains/          one package per business domain
│  │  │  ├─ identity/      User, Role, login
│  │  │  ├─ pdm/           Part, Assembly, the BOM CTE
│  │  │  ├─ qms/           LabTestRecord, metric summaries
│  │  │  ├─ knowledge/     KnowledgeEmbedding, vector search
│  │  │  └─ ecm/ backoffice/ controlling/     (next phases)
│  │  ├─ agents/           graph.py (LangGraph hub-and-spoke), schemas.py (SSE frames)
│  │  ├─ tools/            registry.py, loader.py, mcp_server.py
│  │  ├─ model_registry.py imports every module that declares a table
│  │  └─ main.py           FastAPI + SSE
│  ├─ migrations/          Alembic
│  ├─ tests/               pytest, isolated in its own Postgres schema
│  └─ scripts/{seed,verify}.py
└─ frontend/
   ├─ app/{layout,page}.tsx
   ├─ components/{DashboardShell,AppSidebar,AgentChatSidebar,BOMViewer,QMSMetricsChart}.tsx
   └─ lib/{types,api,agent-stream,utils}.ts
```

Each domain package owns its `models`, `schemas`, `service`, `router` and
`tools`. A domain may import `app.core` and other domains it genuinely depends
on; it must not import `app.agents` or `app.tools`. The dependency runs the
other way, so the tool registry is assembled from the domains rather than the
domains knowing they are exposed as tools.

## Design notes

- **BOM structure is an edge table, not a `parent_id` column.** A `parent_id`
  would cap every part at one parent and be wrong the first time a component is
  reused across assemblies — the normal case for fasteners and shared
  sub-assemblies.
- **BOM traversal is a single recursive CTE**, not Python-side N+1 queries. The
  accumulated path both disambiguates parts appearing under multiple parents and
  guards against a cyclic BOM recursing forever.

- **Revisions are rows; a BOM edge hangs off the parent's revision.** Changing
  what an assembly contains *is* a change to that assembly, so its structure is
  versioned with it. The child end points at the part rather than a revision,
  and the effective child revision resolves at query time to the latest released
  one — pinning every child would make a leaf-level revision bump cascade edits
  all the way up the tree for no engineering reason. `child_revision_id` exists
  for the minority case that genuinely needs one exact revision.

- **EBOM and MBOM are one table under a `bom_type` discriminator.** They share a
  shape — a directed acyclic graph of quantities — and splitting them would mean
  two copies of the traversal, the effectivity logic and the cycle guard.

- **The MBOM is derived, and the differences are stored as instructions.**
  `MBOM = copy(released EBOM) then apply(deltas in sequence)`. The usual
  alternative, copying once and hand-editing the copy forever, loses the reason
  for every difference the moment its author moves on. Here each delta carries a
  required rationale, the gap between the two views is a query, and the MBOM can
  be rebuilt after an engineering change instead of reconciled by hand. A delta
  that no longer matches anything warns rather than failing the rebuild — the
  planner needs to know which instruction went stale.

- **A baseline is a stored snapshot, not a query.** A "baseline" recomputed from
  live tables answers a different question every time it is asked, which makes
  it useless as the thing later states are compared against. The diff keys on
  the full path, so a component appearing under two parents stays two lines.

- **The change workflow is a table-driven state machine.** Transitions live in
  one dict in `domains/ecm/service.py` and are checked at the service layer, so
  an illegal move — approving a draft nobody submitted, releasing an order whose
  request was rejected — fails naming what *was* allowed, instead of succeeding
  quietly and leaving the record incoherent.

- **Every board seat votes separately, and the vote types differ in kind.** A
  rejection sinks the change immediately; a request for information blocks it
  without sinking it, because the board cannot rule on what it has not been
  told; an abstention is a seat with no stake saying so, and neither blocks nor
  endorses. Collapsing these into approve/reject loses the distinction that
  makes a board worth having.

- **Releasing an order is one transaction, and it does not touch the parents.**
  Each affected assembly gets a new revision whose lines are copied forward and
  then edited; the old revision keeps its own lines, so a unit built last year
  still resolves to what it actually contains. Assemblies *above* the change are
  not re-revised — their lines point at the child part and resolve to its latest
  released revision, so they pick up the new one on their own. That is the
  payoff of binding an edge to a parent revision and a child part.

- **The knowledge corpus populates itself from the transactional record.** On
  release, the change order's text is embedded and indexed, so "why is this
  built this way?" is answerable by the same search that serves the hand-written
  documents. If the embedding call fails the release still completes and says
  so — a corpus one document behind is a far better outcome than losing a
  configuration change to a timeout.

- **A serial number is a thing, not a string.** `Unit` gives the physical
  article an identity and `UnitComponent` records what went into *that* one,
  lot by lot. The build record is a snapshot taken at build time, not a view
  over the current BOM: the two diverge the moment a change is released, and
  surviving that divergence is the entire job of a build record. It is also why
  change impact finds affected test evidence through the as-built records —
  asking today's structure would both miss units whose component has since been
  designed out and wrongly implicate units built before it was designed in.

- **Pass/fail is stored, not recomputed.** A reading was judged against a
  specific revision of a specific protocol on the day it was taken. Recomputing
  it against today's limits would silently rewrite history every time a
  specification is tightened — and there is a test that tightens one to prove it
  does not.

- **A non-conformance can be scoped to a lot.** A supplier problem is a property
  of the batch, and forcing it to be recorded against one serial loses the fact
  that every other unit built from that batch is equally suspect. Scope it to
  the lot and the affected units come from the build records.

- **Compliance verdicts are three-valued.** `proven`, `violated`, `unproven` —
  an unassessed component makes a claim unproven, never compliant. A boolean
  would silently convert a gap in supplier data into a statement to a customer.
  For the same reason a total GWP is reported only when every component has a
  figure.
- **The QMS chart uses two Y axes.** Temperature span (~16 K) and pressure drop
  (~850 mbar) differ by two orders of magnitude; on a shared axis the span line
  would flatten against the baseline and hide the ~0.9 K variation that is the
  entire point of looking at it.
- **Metric field names keep the engineering spec's casing**
  (`temperature_span_delta_K`, `cooling_capacity_W`) from ORM column through JSON
  to the React chart, rather than being lower-cased to satisfy PEP 8. The unit
  suffix is part of the metric's identity, and one spelling everywhere removes a
  translation layer that would otherwise need hand-maintaining.
- **Each spoke gets exactly one tool.** A node that could call anything would
  make the routing decision decorative.

- **Agents propose; humans dispose.** A tool declared with an `applier` never
  executes when an agent calls it. Its handler runs as a *preview* that computes
  the diff without writing, the result is filed as an `AgentProposal`, and only
  an approval by a person holding the named role runs the applier. The reviewer
  therefore sees a diff produced by the same code path that will perform the
  change, rather than the model's description of it. `ToolSpec` refuses to
  register an applier without a `required_role`, so a mutation cannot exist that
  anyone is allowed to approve.

- **The audit log is append-only and written in the caller's transaction.**
  `audit.record()` is deliberately not `async` and never commits: a committed
  change without its audit row, or an audit row for a rolled-back change, are
  both states the database should not be able to reach. Correcting a mistaken
  entry means writing another event that says so.

- **`Principal` covers humans and agents alike.** Modelling both as one actor
  type is what lets the audit log, the approval queue, and the eventual CCB
  sign-off sheet share a single notion of "who did this" instead of each
  growing its own nullable `user_id` / `agent_name` pair. Agents carry no roles
  by construction — granting one a role would be a lie the audit log then tells
  forever.

## Known limitations

- **The default JWT signing key is public.** Leave `JWT_SECRET` unset and tokens
  are signed with a value printed in `.env.example`, so anyone can mint an admin
  token. The API warns at boot and `/api/health` reports `secure_tokens: false`
  until you set a real one.
- **All API reads and writes are authenticated.** Health and login are public;
  the Frappe webhook authenticates by HMAC. Browser access tokens last 15
  minutes and refresh through rotating HttpOnly cookies with CSRF checks.
- Re-seeding is required if you change `OPENAI_EMBEDDING_MODEL` to a model of a
  different width — the `Vector(1536)` column would no longer match.
## Enterprise phases 4–7

The complete portfolio workflow is now: supplier receipt → lot genealogy → failed test/NCR → ECR impact analysis → CCB approval → ECO release → revised MBOM/cost → searchable ECN.

Use `MODEL_PROVIDER=stub` for deterministic seeding, tests, and offline evals even when a developer `.env` contains an OpenAI key. The pinned live routing/tool snapshot is `gpt-5-nano-2025-08-07`; all agent writes create approval proposals.

Deployment assets live in `compose.yaml` and `ops/`. Vercel hosts only `frontend`; Neon hosts PostgreSQL/pgvector; the Ubuntu VM hosts the API, worker, scheduler, Redis, MinIO, ERPNext v16, MariaDB and private observability. Copy `.env.production.example` to `.env.production`, set secrets, migrate, seed, and expose only port 8000 through Tailscale Funnel.
