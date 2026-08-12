/**
 * Wire contracts, mirrored by hand from the backend's `schemas.py` files —
 * `app/domains/{pdm,qms,knowledge}/schemas.py` and `app/agents/schemas.py`.
 * If you change a shape there, change it here too.
 *
 * The QMS metric fields keep the engineering spec's casing
 * (`temperature_span_delta_K`, `cooling_capacity_W`) end to end — see the note
 * in backend/app/domains/qms/models.py.
 */

export type MaterialType =
  | "LaFeSi"
  | "Neodymium"
  | "Polymer"
  | "Fluid"
  | "Composite"
  | "Steel"
  | "Assembly";

export type CoatingStatus =
  | "Anti-corrosion metal coating"
  | "Epoxy bonded"
  | "Passivated"
  | "Uncoated"
  | "N/A";

export type DocumentType = "ECO" | "Test Failure" | "Spec" | "Field Report";

export type PartClass =
  | "Mechanical"
  | "Electrical"
  | "Electromechanical"
  | "Software"
  | "Raw material"
  | "Consumable"
  | "Packaging"
  | "Phantom"
  | "Assembly"
  | "Document";

export type LifecycleState =
  | "In design"
  | "In review"
  | "Prototype"
  | "Released"
  | "Obsolete";

export type BomType = "EBOM" | "MBOM";

/**
 * Three-valued on purpose. "Unknown" is not "No" — a component nobody has
 * assessed cannot be counted towards a claim made to a customer.
 */
export type Declaration = "Yes" | "No" | "Unknown";

export type ComplianceStatus =
  | "Compliant"
  | "Non-compliant"
  | "Exempt"
  | "Unknown";

/** How a compliance claim came out across a whole bill of materials. */
export type ComplianceVerdict = "proven" | "violated" | "unproven";

export type IntentName = string;

export type AgentName = string;

// --- PDM -------------------------------------------------------------------

export interface BomNode {
  part_number: string;
  description: string;
  material_type: MaterialType;
  coating_status: CoatingStatus;
  part_class: PartClass;
  revision: string;
  lifecycle_state: LifecycleState;

  quantity: number;
  /** Per one finished unit of the root item, with scrap compounded down. */
  extended_quantity: number;
  unit_of_measure: string;

  /** Position on the drawing. Called what the drawing calls it. */
  find_number: string | null;
  reference_designator: string | null;

  /** MBOM-only; null or default on an EBOM line. */
  operation_seq: number | null;
  is_phantom: boolean;
  scrap_factor: number;

  is_configuration_item: boolean;
  pfas_free: Declaration;
  contains_heavy_rare_earth: Declaration;
  rohs_reach_status: ComplianceStatus;
  gwp_direct: number | null;
  standard_cost: number | null;

  depth: number;
  children: BomNode[];
}

export interface BomResponse {
  root_part_number: string;
  root_revision: string;
  bom_type: BomType;
  /** ISO date the effectivity filter was applied at. */
  as_of: string;
  total_nodes: number;
  max_depth: number;
  tree: BomNode;
}

export interface WhereUsedRow {
  part_number: string;
  description: string;
  part_class: PartClass;
  revision: string;
  lifecycle_state: LifecycleState;
  is_configuration_item: boolean;
  quantity: number;
  depth: number;
  via_part_number: string;
  is_top_level: boolean;
}

export interface WhereUsedResponse {
  part_number: string;
  bom_type: BomType;
  as_of: string;
  total_parents: number;
  top_level_products: string[];
  rows: WhereUsedRow[];
}

export interface ComplianceGap {
  part_number: string;
  description: string;
  attribute: string;
  value: string;
}

export interface ComplianceRollup {
  root_part_number: string;
  bom_type: BomType;
  as_of: string;
  components_assessed: number;
  pfas_free: ComplianceVerdict;
  heavy_rare_earth_free: ComplianceVerdict;
  rohs_reach: ComplianceVerdict;
  /** Null when any component has no figure — a partial total would mislead. */
  total_direct_gwp: number | null;
  gaps: ComplianceGap[];
  violations: ComplianceGap[];
}

export interface BaselineOut {
  id: string;
  name: string;
  platform: string | null;
  bom_type: BomType;
  captured_at: string;
  eco_id: string | null;
  notes: string | null;
  line_count: number;
}

export interface BaselineDiffRow {
  kind: "added" | "removed" | "changed";
  /** Full path, so a shared component's two occurrences stay distinct. */
  path: string;
  part_number: string;
  field: string | null;
  before: string | null;
  after: string | null;
}

export interface BaselineDiff {
  from_baseline: string;
  to_baseline: string;
  added: BaselineDiffRow[];
  removed: BaselineDiffRow[];
  changed: BaselineDiffRow[];
  unchanged_count: number;
}

// --- QMS -------------------------------------------------------------------

export type UnitStatus =
  | "In production"
  | "In test"
  | "Shipped"
  | "In field"
  | "Returned"
  | "Scrapped";

/** "Not evaluated" means no protocol was in force — data, but not a verdict. */
export type TestResult = "Pass" | "Fail" | "Not evaluated";

export interface MetricBreach {
  metric: string;
  unit: string;
  value: number;
  lower_limit: number | null;
  upper_limit: number | null;
}

export interface LabTestRecord {
  recorded_at: string;
  temperature_span_delta_K: number;
  pressure_drop_mbar: number;
  magnetization_cycles_hz: number;
  cooling_capacity_W: number;
  result: TestResult;
  breaches: MetricBreach[];
  test_rig: string | null;
  operator: string | null;
}

export interface MetricSummary {
  metric: string;
  unit: string;
  minimum: number;
  maximum: number;
  mean: number;
  latest: number;
  /** Null when the protocol sets no bound on that side. */
  lower_limit: number | null;
  upper_limit: number | null;
}

export interface QmsResponse {
  serial_number: string;
  part_number: string | null;
  built_to_revision: string | null;
  status: UnitStatus | null;
  protocol: string | null;
  sample_count: number;
  pass_count: number;
  fail_count: number;
  records: LabTestRecord[];
  summaries: MetricSummary[];
}

// --- As-built traceability -------------------------------------------------

export interface GenealogyLine {
  part_number: string;
  description: string;
  revision: string | null;
  quantity: number;
  unit_of_measure: string;
  lot_number: string | null;
  supplier_lot: string | null;
  child_serial_number: string | null;
  position: string | null;
  operation_seq: number | null;
  installed_at: string | null;
  depth: number;
  parent_serial: string;
}

/** What one individual article contains — not what the current BOM says. */
export interface UnitGenealogy {
  serial_number: string;
  part_number: string;
  built_to_revision: string | null;
  status: UnitStatus;
  built_at: string | null;
  plant: string | null;
  customer_ref: string | null;
  as_built_baseline: string | null;
  line_count: number;
  lots: string[];
  lines: GenealogyLine[];
}

export interface TracedUnit {
  serial_number: string;
  part_number: string;
  status: string;
  built_at: string | null;
  customer_ref: string | null;
  /** 0 when the unit holds the lot directly, higher through a sub-assembly. */
  depth: number;
}

export interface LotTrace {
  lot_number: string;
  unit_count: number;
  units: TracedUnit[];
}

// --- Knowledge -------------------------------------------------------------

export interface KnowledgeHit {
  document_type: DocumentType;
  text_content: string;
  source_ref: string | null;
  related_part_number: string | null;
  /**
   * Cosine similarity, or null when the hit came from a full-text match alone
   * or the deterministic fallback provider is in use. Null means there is no
   * score to report — never substitute a number for it.
   */
  similarity: number | null;
  chunk_id: string | null;
  source_document_id: string | null;
  revision: string | null;
  page: number | null;
  sheet: string | null;
  heading: string | null;
  rrf_score: number | null;
}

export interface KnowledgeResponse {
  query: string;
  provider: string;
  /** False when the backend is running the deterministic embedding fallback. */
  semantic: boolean;
  hits: KnowledgeHit[];
}

// --- Health ----------------------------------------------------------------

export interface HealthResponse {
  status: string;
  embedding_provider: string;
  semantic_search: boolean;
  model_client: string;
  live_model: boolean;
  /** False while the built-in development JWT signing key is in use. */
  secure_tokens: boolean;
  adapter: string;
  adapter_status: string;
  adapter_detail: string | null;
  last_synchronization: string | null;
  queue_depth: number;
  degraded_mode: boolean;
}

// --- SSE frames ------------------------------------------------------------

export interface AgentStateFrame {
  run_id: string | null;
  correlation_id: string | null;
  agent: AgentName;
  status: "thinking" | "delegating" | "calling_tool" | "done";
  detail: string | null;
}

export interface TokenFrame {
  run_id: string | null;
  correlation_id: string | null;
  text: string;
}

export interface ToolResultFrame {
  run_id: string | null;
  correlation_id: string | null;
  tool: string;
  payload: unknown;
}

export interface FinalFrame {
  run_id: string | null;
  correlation_id: string | null;
  text: string;
  intent: IntentName;
  tool_calls: string[];
  domains: string[];
  citations: Array<{source_ref:string;revision:string|null;page:number|null;sheet:string|null;heading:string|null}>;
  proposal_summaries: Array<{proposal_id:string;summary:string;required_role:string}>;
}

export interface ErrorFrame {
  run_id: string | null;
  correlation_id: string | null;
  message: string;
  recoverable: boolean;
}

export type AgentEvent =
  | { event: "agent_state"; data: AgentStateFrame }
  | { event: "token"; data: TokenFrame }
  | { event: "tool_result"; data: ToolResultFrame }
  | { event: "final"; data: FinalFrame }
  | { event: "error"; data: ErrorFrame };

// --- Chat UI ---------------------------------------------------------------

export interface ChatTurn {
  role: "user" | "assistant";
  content: string;
}

// --- Overview --------------------------------------------------------------

export interface ShowcaseCounts {
  controlled_parts: number;
  built_units: number;
  test_samples: number;
  failed_samples: number;
  open_ncrs: number;
  low_stock_items: number;
  indexed_documents: number;
  pending_proposals: number;
}

export interface WorkflowStep {
  domain: string;
  title: string;
  reference: string;
  detail: string;
  status: string;
  href: string;
}

export interface ShowcaseResponse {
  generated_at: string;
  product: string;
  product_number: string;
  counts: ShowcaseCounts;
  workflow: WorkflowStep[];
}

// --- Engineering change ----------------------------------------------------

export interface CcbReview {
  seat: string;
  reviewer_label: string;
  decision: string;
  comment: string | null;
  decided_at: string | null;
}

export interface Quorum {
  required_seats: string[];
  voted_seats: string[];
  missing_seats: string[];
  rejecting_seats: string[];
  blocking_seats: string[];
  satisfied: boolean;
  verdict: string;
}

export interface AffectedAssembly {
  part_number: string;
  revision: string;
  depth: number;
  quantity: number;
}

export interface AffectedProduct {
  part_number: string;
  description: string;
  revision: string;
  reached_via: string[];
}

export interface AffectedDocument {
  document_number: string;
  title: string;
  kind: string;
  latest_revision: string | null;
}

export interface RevalidationTarget {
  serial_number: string;
  part_number: string;
  sample_count: number;
  latest_recorded_at: string | null;
}

export interface CostImpactRow {
  part_number: string;
  baseline_from: string | null;
  baseline_to: string | null;
  before: number | null;
  after: number | null;
  delta: number | null;
  note: string | null;
}

export interface ImpactFindings {
  affected_items: string[];
  affected_assemblies: AffectedAssembly[];
  affected_products: AffectedProduct[];
  affected_documents: AffectedDocument[];
  revalidation_required: RevalidationTarget[];
  affected_baselines: string[];
  configuration_items: string[];
  cost_impact: CostImpactRow[];
  gaps: string[];
}

export interface ImpactAssessment {
  id: string;
  generated_at: string;
  generated_by: string;
  summary: string;
  findings: ImpactFindings;
}

export interface ChangeRequest {
  id: string;
  number: string;
  title: string;
  problem_statement: string;
  proposed_solution: string | null;
  preliminary_impact: string | null;
  originator_label: string | null;
  origin: string;
  priority: string;
  status: string;
  created_at: string;
  submitted_at: string | null;
  decided_at: string | null;
  affected_part_numbers: string[];
  reviews: CcbReview[];
  quorum: Quorum | null;
  latest_assessment: ImpactAssessment | null;
}

// --- Controlling -----------------------------------------------------------

export interface MaterialCostLine {
  part_number: string;
  extended_quantity: number;
  standard_cost: number | null;
  extended_cost: number | null;
}

export interface LabourCostLine {
  operation_seq: number;
  work_center: string;
  minutes_per_unit: number;
  hourly_rate: number;
  cost: number;
}

export interface CostRollup {
  part_number: string;
  revision: string;
  batch_size: number;
  material_cost: number;
  labour_cost: number;
  total_cost: number;
  currency: string;
  materials: MaterialCostLine[];
  labour: LabourCostLine[];
}

// --- Supply and business ---------------------------------------------------

export interface Opportunity {
  id: string;
  title: string;
  customer_name: string;
  stage: string;
  value: number;
  currency: string;
  expected_close: string | null;
}

export interface StockRisk {
  part_number: string;
  description: string | null;
  on_hand: number;
  allocated: number;
  available: number;
  reorder_level: number;
  low_stock: boolean;
  lead_time_days: number | null;
}

export interface PurchaseOrderLine {
  line_number: number;
  part_number: string;
  quantity: number;
  received_quantity: number;
  unit_price: number;
}

export interface PurchaseOrder {
  order_number: string;
  supplier: string;
  supplier_code: string;
  status: string;
  ordered_at: string;
  required_date: string | null;
  currency: string;
  value: number;
  lines: PurchaseOrderLine[];
}

export interface DeployedUnit {
  serial_number: string;
  part_number: string;
  unit_status: string;
  customer_name: string;
  site_name: string;
  address: string | null;
  commissioned_at: string | null;
  status: string;
}

export interface FieldEvent {
  id: string;
  serial_number: string;
  customer_name: string;
  occurred_at: string;
  event_type: string;
  summary: string;
  resolution: string | null;
}

export interface TrlGate {
  id: string;
  work_package: string;
  programme: string | null;
  trl: number;
  trl_target: number;
  status: string;
  evidence: string | null;
  approved_by: string | null;
}

export interface Deliverable {
  code: string;
  title: string;
  work_package: string;
  programme: string;
  due_date: string;
  status: string;
}

export interface CalibrationRecord {
  id: string;
  asset_tag: string;
  asset_name: string;
  location: string | null;
  certificate_number: string;
  calibrated_at: string;
  valid_until: string;
  result: string;
  overdue: boolean;
  due_soon: boolean;
}

export interface AssetBooking {
  id: string;
  asset_tag: string;
  asset_name: string;
  starts_at: string;
  ends_at: string;
  booked_by: string | null;
  purpose: string;
  status: string;
}

export interface CapacityRow {
  user_id: string;
  engineer: string | null;
  week_start: string;
  available_hours: number;
  allocated_hours: number;
  remaining_hours: number;
  overloaded: boolean;
  packages: Array<{ work_package: string; hours: number }>;
}

export interface TimesheetRow {
  id: string;
  engineer: string;
  work_package: string | null;
  work_date: string;
  hours: number;
  description: string | null;
}

/** The picker row on the quality screens. */
export interface UnitSummary {
  serial_number: string;
  part_number: string;
  built_to_revision: string | null;
  status: UnitStatus;
  built_at: string | null;
  plant: string | null;
  customer_ref: string | null;
  sample_count: number;
  fail_count: number;
}

export interface CapaAction {
  kind: string;
  description: string;
  owner_label: string | null;
  due_date: string | null;
  completed_at: string | null;
  effectiveness_check: string | null;
}

export interface NonConformance {
  id: string;
  number: string;
  title: string;
  description: string;
  source: string;
  severity: string;
  status: string;
  disposition: string;
  disposition_note: string | null;
  serial_number: string | null;
  part_number: string | null;
  lot_number: string | null;
  raised_by_label: string;
  raised_at: string;
  closed_at: string | null;
  escalated_ecr_number: string | null;
  affected_units: string[];
  actions: CapaAction[];
}

export interface IngestionRow {
  id: string;
  filename: string;
  version: number;
  status: string;
  error: string | null;
}

// --- Agents and control ----------------------------------------------------

/** One field- or row-level difference a proposal would make. */
export interface ProposedChange {
  kind: "add" | "remove" | "modify" | string;
  /** What is changing, e.g. `BomEdge ECL-AMR-200 -> LFS-POR-010`. */
  target: string;
  field: string | null;
  before: unknown;
  after: unknown;
}

/** What a mutating tool returns instead of performing its mutation. */
export interface ProposalPreview {
  summary: string;
  entity_type: string;
  entity_ref: string | null;
  changes: ProposedChange[];
  warnings: string[];
}

export interface Proposal {
  id: string;
  created_at: string;
  proposed_by_agent: string;
  tool_name: string;
  arguments: Record<string, unknown>;
  summary: string;
  preview: ProposalPreview;
  required_role: string;
  status: string;
  reviewed_by: string | null;
  reviewed_at: string | null;
  review_note: string | null;
  applied_at: string | null;
  result: Record<string, unknown> | null;
}

export interface AgentRun {
  id: string;
  correlation_id: string;
  status: string;
  domains: string[];
  model: string | null;
  duration_ms: number | null;
  started_at: string;
}

export interface AuditEvent {
  id: string;
  occurred_at: string;
  actor_type: string;
  actor_label: string | null;
  action: string;
  entity_type: string;
  entity_id: string | null;
  before: Record<string, unknown> | null;
  after: Record<string, unknown> | null;
  reason: string | null;
  correlation_id: string | null;
}

export interface EvalCase {
  case_name: string;
  category: string;
  passed: boolean;
  score: number;
  detail: string | null;
}

export interface EvalRun {
  id: string;
  suite: string;
  status: string;
  passed: number;
  failed: number;
  metrics: Record<string, number> | null;
  started_at: string;
  cases: EvalCase[];
}
