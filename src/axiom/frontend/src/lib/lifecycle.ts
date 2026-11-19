export type LifeStage =
  | "draft" | "intake" | "modeling" | "equations" | "solving" | "analyzing"
  | "review" | "decided" | "archived" | "closed" | "on_hold" | "blocked" | "rejected" | "reopened"

export type LifeCard = {
  id: number
  project_id: number | null
  workspace_id: number
  title: string
  description: string
  tags: string[]
  priority: string
  owner_id: number
  owner_name: string
  due_at: string | null
  custom_fields: Record<string, string | number | boolean | null>
  stage: LifeStage
  resume_stage: string
  auto_advance: boolean
  approval_required: boolean
  favorite: boolean
  deleted_at: string | null
  ai_summary: string
  ai_summary_en: string
  next_action: string
  next_action_en: string
  next_stage: string | null
  baseline_model_id: number | null
  best_objective: number | null
  run_count: number
  last_activity: string | null
  role: string
  created_at: string
  updated_at: string
}

export type LifeModel = {
  id: number
  semver: string
  label: string
  baseline: boolean
  note: string
  statement: string
  aml: string
  equations: { latex?: string; matrix_latex?: string; sense?: string }
  latex: string
  exports: Record<string, string>
  created_at: string
}

export type LifeRun = {
  id: number
  solver: string
  algorithm: string
  parameters: Record<string, unknown>
  seed: number | null
  wall_ms: number
  status: string
  sense: string
  objective: number | null
  solution: Record<string, number>
  duals: Record<string, number>
  iis: Record<string, unknown>
  log: string
  note: string
  model_revision_id: number | null
  created_at: string
}

export type LifeDetail = LifeCard & {
  requirements: { id: number; text: string; text_en: string; done: boolean; source: string; sort: number }[]
  members: { user_id: number; username: string; display_name: string; role: string }[]
  transitions: { id: number; from_stage: string; to_stage: string; comment: string; actor_kind: string; actor_name: string; created_at: string }[]
  requests: { id: number; from_stage: string; to_stage: string; comment: string; status: string; actor_name: string; role: string }[]
  data: { id: number; name: string; filename: string; schema: { name: string; type: string }[]; content: string; version: number; parent_id: number | null; note: string }[]
  models: LifeModel[]
  runs: LifeRun[]
  analyses: { id: number; kind: string; status: string; note: string; result: Record<string, unknown>; created_at: string }[]
  decisions: { id: number; title: string; rationale: string; rationale_en: string; status: string; chosen_run_id: number | null; created_at: string }[]
  changes: { id: number; title: string; impact: string; from_stage: string; status: string; created_at: string }[]
  artifacts: { id: number; kind: string; name: string; media: string; bytes: number; content?: string; created_at: string }[]
  activities: { id: number; actor_kind: string; actor_name: string; action: string; detail: string; detail_en: string; created_at: string }[]
  notice?: { kind: string; title: string; title_en: string; body: string; body_en: string } | null
  applied?: boolean
}

export type LifeNotice = { id: number; problem_id: number | null; kind: string; title: string; title_en: string; body: string; body_en: string }
export type LifeView = { id: number; name: string; filters: Record<string, unknown> }
export type LifeTemplate = { id: string; title_zh: string; title_en: string; summary_zh: string; summary_en: string; category: string; tag: string }
export type LifeSearch = {
  problems: { id: number; title: string; stage: string; snippet: string }[]
  models: { problem_id: number; id: number; semver: string; title: string; snippet: string }[]
  runs: { problem_id: number; id: number; solver: string; title: string; snippet: string }[]
}

export const MAIN_STAGES: LifeStage[] = ["draft", "intake", "modeling", "equations", "solving", "analyzing", "review", "decided", "archived", "closed"]
export const SIDE_STAGES: LifeStage[] = ["on_hold", "blocked", "rejected", "reopened"]
