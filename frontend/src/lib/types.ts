export type User = {
  id: number
  username: string
  display_name: string
  role: string
  locale: string
  theme: string
  created_at: string
}

export type Project = {
  id: number
  workspace_id: number
  title: string
  statement: string
  dsl: string
  locale: string
  status: string
  created_by: number
  created_at: string
  updated_at: string
}

export type Member = {
  user_id: number
  username: string
  display_name: string
  role: string
}

export type Workspace = {
  id: number
  name: string
  owner_id: number
  created_at: string
  members: Member[]
}

export type RunEvent = {
  id: number
  run_id: number
  seq: number
  agent: string
  kind: string
  title: string
  title_en: string
  detail: string
  detail_en: string
  status: string
  created_at: string
}

export type Run = {
  id: number
  project_id: number
  status: string
  solver: string
  objective: string
  statement: string
  dsl: string
  error: string
  error_en: string
  auto_approve: boolean
  pending_gate: { id: number; gate: string; status: string } | null
  result: ResultPayload
  created_by: number
  created_at: string
  finished_at: string | null
}

export type ResultPayload = {
  formulation?: { title?: string; summary?: string; summary_en?: string; kind?: string; questions?: string[] }
  dsl?: string
  alternative_dsl?: string
  solver?: string
  objective?: number | null
  status?: string
  variables?: Record<string, number>
  constraints?: ConstraintRow[]
  race?: RaceRow[]
  verification?: { ok?: boolean; message?: string; message_en?: string; delta?: number | null }
  views?: { bars?: { name: string; value: number }[]; gantt?: GanttRow[] | null; network?: NetworkView | null }
  statistics?: Record<string, number | null>
  sensitivity?: { rows?: SensitivityRow[]; base?: number }
  scenarios?: ScenarioRow[]
  duals?: Record<string, number>
  reduced_costs?: Record<string, number>
  figures?: { feasible_region?: FeasibleRegion | null; pareto?: ParetoFront | null }
  monte_carlo?: { samples?: number; mean?: number; std?: number; p05?: number; p95?: number; values?: number[] }
  translations?: Record<string, { code?: string; filename?: string; error?: string }>
  simulation?: SimulationResult
  diagnosis?: {
    message?: string
    message_en?: string
    slacks?: { name: string; value: number }[]
    total_violation?: number
    conflicts?: { constraint: string; label: string; suggestion: string; suggestion_en: string; slack?: number }[]
  }
  summary?: string
  summary_en?: string
  title?: string
  questions?: string[]
  kind?: string
  standard_form?: StandardForm
}

export type StandardEquation = {
  id: string
  role: string
  name?: string
  constraint?: string | null
  key?: string
  latex: string
  plain: string
  domain?: string
}

export type StandardForm = {
  ok: boolean
  kind?: string
  sense?: string
  message?: string
  message_en?: string
  code?: string
  latex?: string
  plain?: string
  plain_en?: string
  mathml?: string
  matrix_latex?: string
  equations?: StandardEquation[]
  indexed?: { constraint: string; latex: string; plain: string }[]
  maps?: { equation_id: string; constraint: string; key: string }[]
  canonical?: {
    applicable: boolean
    note_zh?: string
    note_en?: string
    latex?: string
    plain?: string
  }
}

export type ConstraintRow = {
  name: string
  sense: string
  lhs: number
  rhs: number
  slack: number
  binding: boolean
  violated: boolean
}

export type RaceRow = {
  solver: string
  status: string
  objective: number | null
  runtime_sec?: number
  message?: string
}

export type SensitivityRow = { name: string; low: number; base: number; high: number; span: number }
export type ScenarioRow = { name: string; status: string; objective: number | null; variables?: Record<string, number> }
export type FeasibleRegion = {
  x: string
  y: string
  polygon: number[][]
  lines?: { name: string; points: number[][] }[]
  optimum?: { x?: number | null; y?: number | null } | null
}
export type ParetoFront = { x: string; y: string; x_sense?: string; y_sense?: string; points: { weight: number; x: number; y: number }[] }
export type GanttRow = { id: string; start: number; end: number; duration: number }
export type NetworkView = { nodes: { id: string; group: string }[]; edges: { source: string; target: string; value: number }[] }
export type SimulationResult = {
  served: number
  avg_wait: number
  avg_sojourn: number
  utilization: number
  timeline: { t: number; wait: number; served: number }[]
  servers: number
  arrival_rate: number
  service_rate: number
}

export type SolverInfo = {
  name: string
  label: string
  available: boolean
  version: string
  capabilities: string[]
  license: string
  detail: string
  classes?: string[]
  features?: string[]
  license_type?: string
  license_state?: string
  distribution?: string
  bundled?: boolean
  docs_url?: string
}

export type BenchmarkRow = {
  class: string
  solver: string
  status: string
  objective: number | null
  expected: number
  runtime_sec: number
  agree: boolean
  message?: string
}

export type TemplateInfo = {
  id: string
  title_zh: string
  title_en: string
  summary_zh: string
  summary_en: string
  kind: string
  category: string
  dsl?: string
}

export type AuditRow = {
  id: number
  username: string
  action: string
  entity: string
  entity_id: string
  detail: string
  created_at: string
}

export type Dashboard = {
  projects: number
  runs: number
  completed: number
  solvers_available: number
  solvers: SolverInfo[]
  recent_projects: Project[]
  recent_runs: Run[]
}

export type Settings = {
  provider: string
  base_url: string
  model: string
  api_key_set: boolean
  api_key_mask: string
}

export type ProviderModel = {
  id: string
  label: string
  context: number
  tools: boolean
  json_mode: boolean
  vision: boolean
  reasoning: boolean
  input_usd_per_mtok: number
  output_usd_per_mtok: number
  custom?: boolean
  fetched?: boolean
}

export type ProviderCard = {
  id: string
  name: string
  name_zh: string
  group: "domestic" | "international" | "aggregator" | "local"
  protocol: string
  auth: string
  base_url: string
  default_base_url: string
  enabled: boolean
  model: string
  models: ProviderModel[]
  key_set: boolean
  key_mask: string
  secret_set: boolean
  key_optional: boolean
  proxy: string
  timeout: number
  api_version: string
  region: string
  api_style: string
  bedrock_mode: string
  notes: string
  notes_zh: string
  monogram: string
  color: string
  builtin: boolean
  listable: boolean
  supports: { tools: boolean; json_mode: boolean; vision: boolean; reasoning: boolean }
}

export type RoleAssignment = { chain: { provider: string; model: string }[]; compete: boolean }

export type UsageRow = {
  at: string
  role: string
  provider: string
  model: string
  prompt_tokens: number
  completion_tokens: number
  cost_usd: number
  latency_ms: number
  ok: boolean
  error?: string
}

export type LlmDirectory = {
  groups: { id: string; providers: ProviderCard[] }[]
  roles: Record<string, RoleAssignment>
  usage: {
    rows: UsageRow[]
    totals: { calls: number; prompt_tokens: number; completion_tokens: number; cost_usd: number }
    by_provider: Record<string, { calls: number; prompt_tokens: number; completion_tokens: number; cost_usd: number }>
  }
  active: { provider: string; base_url: string; model: string }
}

export type ProviderTestResult = {
  ok: boolean
  provider: string
  model?: string
  latency_ms: number
  message: string
  message_en: string
  code?: string
}
