export type StudyPoint = {
  id: string
  label?: string
  values?: Record<string, number | null>
  objectives?: Record<string, number | null>
  feasible?: boolean
  minimize?: number[]
  violation?: number
}

export type Study = {
  ok?: boolean
  kind?: string
  message?: string
  message_en?: string
  note?: string
  note_en?: string
  objective?: number | null
  status?: string
  violation?: number
  architecture?: string
  method?: string
  beta?: number
  probability?: number
  hypervolume?: number | null
  points?: StudyPoint[]
  pareto?: StudyPoint[]
  rows?: Array<Record<string, number | string | null>>
  tornado?: Array<{ name: string; low: number | null; high: number | null; base: number }>
  surface?: { x: number[]; y: number[]; z: number[][]; xlabel: string; ylabel: string; zlabel: string } | null
  effects?: {
    main: Array<{ name: string; levels: Array<{ x: number; mean: number }> }>
    interaction?: { a: string; b: string; low: Array<{ x: number; y: number }>; high: Array<{ x: number; y: number }> } | null
  }
  correlation?: { labels: string[]; matrix: number[][] }
  values?: number[]
  histogram?: { edges: number[]; counts: number[] }
  convergence?: Array<{ objective?: number | null; violation?: number | null; residual?: number | null }>
  history?: Array<{ objective?: number | null; violation?: number | null; residual?: number | null }>
  n2?: { labels: string[]; cells: Array<{ row: number; col: number; from: string; to: string; variables: string[]; kind: string }> }
  gantt?: Array<{ id: string; start: number; end: number; duration?: number }>
  units?: Record<string, string>
  columns?: Array<{ key: string; label: string; unit?: string }>
  summary_metrics?: Record<string, unknown>
  surrogate?: { cv?: { r2?: number | null; rmse?: number | null; mae?: number | null }; error?: string; error_en?: string }
  duals?: Record<string, number>
  reduced_costs?: Record<string, number>
  objective_ranging?: Array<Record<string, unknown>>
  rhs_ranging?: Array<Record<string, unknown>>
  design?: Record<string, number>
  disciplines?: Array<{ name: string; outputs: Record<string, number>; constraints: Array<{ name: string; value: number }> }>
  iis?: { feasible?: boolean; constraints?: string[]; message?: string; message_en?: string } | null
  quality?: Record<string, number>
  variables?: Record<string, number>
  title_zh?: string
  title_en?: string
  library?: string
  samples?: number
}

export type AnalysisProposal = {
  kind: string
  reason_zh: string
  reason_en: string
  options?: Record<string, unknown>
  confidence?: number
  matched?: string[]
}

export type AnalysisJob = {
  id: string
  kind: string
  status: string
  progress: number
  message: string
  message_en: string
  error: string
  error_en: string
  result: Study | null
  run_id?: number | null
}

export type CompatibilityCell = {
  axis: string
  class: string
  name: string
  status: string
  agree?: boolean
  reason: string
  reason_en: string
}

export type CompatibilityReport = {
  ok?: boolean
  execute?: boolean
  classes: string[]
  solvers: CompatibilityCell[]
  languages: CompatibilityCell[]
  summary: Record<string, number>
}
