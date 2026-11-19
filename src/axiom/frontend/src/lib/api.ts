import type { AnalysisJob, AnalysisProposal, CompatibilityReport, Study } from "@/components/analysis/types"
import type { LifeCard, LifeDetail, LifeNotice, LifeSearch, LifeTemplate, LifeView } from "@/lib/lifecycle"
import type { AuditRow, BenchmarkRow, Dashboard, FeasibleRegion, LlmDirectory, ParetoFront, Project, ProviderCard, ProviderTestResult, RoleAssignment, Run, RunEvent, Settings, SolverInfo, StandardForm, TemplateInfo, User, Workspace } from "@/lib/types"

const TOKEN = "axiom_token"

export class ApiError extends Error {
  messageEn: string
  status: number

  constructor(message: string, messageEn: string, status: number) {
    super(message)
    this.name = "ApiError"
    this.messageEn = messageEn
    this.status = status
  }
}

export function token() {
  return localStorage.getItem(TOKEN)
}

export function setToken(value: string | null) {
  if (value) localStorage.setItem(TOKEN, value)
  else localStorage.removeItem(TOKEN)
}

function acceptBase(value: unknown) {
  if (typeof value !== "string") return ""
  const trimmed = value.trim().replace(/\/$/, "")
  return /^http:\/\/(127\.0\.0\.1|localhost):\d{1,5}$/.test(trimmed) ? trimmed : ""
}

let basePromise: Promise<string> | null = null

export function noteApiBase(value: string) {
  const accepted = acceptBase(value)
  if (!accepted) {
    basePromise = null
    return ""
  }
  basePromise = Promise.resolve(accepted)
  return accepted
}

async function loadApiBase() {
  const bridge = typeof window !== "undefined" ? window.axiom : undefined
  if (bridge?.getApiBase) {
    const value = await Promise.race([
      bridge.getApiBase(),
      new Promise<string>((resolve) => setTimeout(() => resolve(""), 45000)),
    ])
    return acceptBase(value)
  }
  return acceptBase(bridge?.apiBase)
}

export function resolveApiBase() {
  if (!basePromise) {
    basePromise = loadApiBase().then((value) => {
      if (!value) basePromise = null
      return value
    })
  }
  return basePromise
}

async function apiRoot() {
  return resolveApiBase()
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  path = (await apiRoot()) + path
  const headers = new Headers(init.headers)
  if (init.body && !headers.has("Content-Type")) headers.set("Content-Type", "application/json")
  const current = token()
  if (current) headers.set("Authorization", `Bearer ${current}`)
  const response = await fetch(path, { ...init, headers })
  if (response.status === 204) return undefined as T
  const contentType = response.headers.get("content-type") || ""
  if (!response.ok) {
    let message = response.statusText
    let messageEn = response.statusText
    if (contentType.includes("json")) {
      const body = await response.json()
      message = body.message || message
      messageEn = body.message_en || message
    }
    throw new ApiError(message, messageEn, response.status)
  }
  if (!contentType.includes("json")) return (await response.blob()) as T
  return response.json() as Promise<T>
}

export const api = {
  login: async (username: string, password: string) => {
    const bridge = typeof window !== "undefined" ? window.axiom : undefined
    const base = await resolveApiBase()
    if (!base && bridge?.getApiBase) {
      const status = bridge.sidecarStatus ? await bridge.sidecarStatus().catch(() => null) : null
      const detail = status?.detail ? ` ${status.detail}` : ""
      throw new ApiError(
        `求解服务没有响应，侧车可能已经退出。${detail}`.trim(),
        `The solver service is not responding. The sidecar may have exited.${detail}`.trim(),
        0,
      )
    }
    try {
      const result = await request<{ token: string; user: User }>("/api/auth/login", {
        method: "POST",
        body: JSON.stringify({ username, password }),
      })
      if (!result || typeof result !== "object" || !("token" in result) || !result.user) {
        throw new ApiError(
          "求解服务没有响应，侧车可能已经退出。登录接口没有返回账号。",
          "The solver service is not responding. The sidecar may have exited. Login did not return an account.",
          0,
        )
      }
      return result
    } catch (error) {
      if (error instanceof ApiError) throw error
      const raw = error instanceof Error ? error.message : String(error)
      throw new ApiError(
        `求解服务没有响应，侧车可能已经退出。 ${raw}`.trim(),
        `The solver service is not responding. The sidecar may have exited. ${raw}`.trim(),
        0,
      )
    }
  },
  logout: () => request<{ ok: boolean }>("/api/auth/logout", { method: "POST" }),
  me: () => request<User>("/api/auth/me"),
  updateMe: (body: Partial<Pick<User, "display_name" | "locale" | "theme">> & { password?: string }) =>
    request<User>("/api/auth/me", { method: "PATCH", body: JSON.stringify(body) }),
  dashboard: () => request<Dashboard>("/api/dashboard"),
  workspaces: () => request<Workspace[]>("/api/workspaces"),
  createWorkspace: (name: string) => request<Workspace>("/api/workspaces", { method: "POST", body: JSON.stringify({ name }) }),
  addMember: (workspaceId: number, username: string) =>
    request<Workspace>(`/api/workspaces/${workspaceId}/members`, { method: "POST", body: JSON.stringify({ username }) }),
  users: () => request<User[]>("/api/users"),
  createUser: (body: { username: string; password: string; display_name: string; role: string }) =>
    request<User>("/api/users", { method: "POST", body: JSON.stringify(body) }),
  projects: () => request<Project[]>("/api/projects"),
  project: (id: number) => request<Project>(`/api/projects/${id}`),
  createProject: (body: { title: string; statement?: string; dsl?: string; workspace_id?: number; locale?: string }) =>
    request<Project>("/api/projects", { method: "POST", body: JSON.stringify(body) }),
  updateProject: (id: number, body: Partial<Pick<Project, "title" | "statement" | "dsl" | "locale">>) =>
    request<Project>(`/api/projects/${id}`, { method: "PATCH", body: JSON.stringify(body) }),
  deleteProject: (id: number) => request<{ ok: boolean }>(`/api/projects/${id}`, { method: "DELETE" }),
  runs: (projectId: number) => request<Run[]>(`/api/projects/${projectId}/runs`),
  startRun: (projectId: number, body: { statement?: string; dsl?: string; solver?: string; algorithm?: string; auto_approve?: boolean; locale?: string }) =>
    request<Run>(`/api/projects/${projectId}/runs`, { method: "POST", body: JSON.stringify(body) }),
  run: (id: number) => request<Run>(`/api/runs/${id}`),
  events: (id: number, after = 0) => request<RunEvent[]>(`/api/runs/${id}/events?after=${after}`),
  decide: (id: number, decision: "approved" | "rejected", note = "") =>
    request<Run>(`/api/runs/${id}/decision`, { method: "POST", body: JSON.stringify({ decision, note }) }),
  cancelRun: (id: number) => request<Run>(`/api/runs/${id}/cancel`, { method: "POST" }),
  chat: (messages: { role: string; content: string }[], projectId?: number) =>
    request<{ role: string; content: string; provider: string; proposals?: AnalysisProposal[]; study?: Study | null; lifecycle?: { problem_id: number; project_id: number | null; stage: string; title: string } }>("/api/chat", { method: "POST", body: JSON.stringify({ messages, project_id: projectId }) }),
  validate: (dsl: string) => request<{ ok: boolean; aml?: string; diagnostics: { level: string; message: string; message_en: string; line?: number; code?: string }[] }>("/api/validate", { method: "POST", body: JSON.stringify({ dsl }) }),
  standardForm: (dsl: string) => request<StandardForm>("/api/standard-form", { method: "POST", body: JSON.stringify({ dsl }) }),
  translate: (dsl: string, target: string) => request<{ code: string; filename: string; language: string }>("/api/translate", { method: "POST", body: JSON.stringify({ dsl, target }) }),
  importModel: (format: string, text: string) => request<{ ok: boolean; aml: string; diagnostics: { message: string }[] }>("/api/import", { method: "POST", body: JSON.stringify({ format, text }) }),
  templates: () => request<TemplateInfo[]>("/api/templates"),
  template: (id: string) => request<TemplateInfo>(`/api/templates/${id}`),
  solvers: () => request<SolverInfo[]>("/api/solvers"),
  translators: () => request<{ name: string; language: string; filename: string }[]>("/api/translators"),
  benchmark: () => request<{ rows: BenchmarkRow[]; seconds: number; classes: string[] }>("/api/benchmark", { method: "POST" }),
  compatibility: (execute = false) => request<CompatibilityReport>(`/api/compatibility?execute=${execute ? "true" : "false"}`),
  proposeAnalysis: (body: { statement?: string; dsl?: string }) =>
    request<{ proposals: AnalysisProposal[]; auto: AnalysisProposal | null }>("/api/analyses/propose", { method: "POST", body: JSON.stringify(body) }),
  runAnalysis: (body: { kind: string; dsl?: string; options?: Record<string, unknown> }) =>
    request<Study>("/api/analyses/run", { method: "POST", body: JSON.stringify(body) }),
  startAnalysis: (body: { kind: string; dsl?: string; statement?: string; project_id?: number; options?: Record<string, unknown> }) =>
    request<AnalysisJob>("/api/analyses", { method: "POST", body: JSON.stringify(body) }),
  analysisJob: (id: string) => request<AnalysisJob>(`/api/analyses/${id}`),
  cancelAnalysis: (id: string) => request<AnalysisJob>(`/api/analyses/${id}/cancel`, { method: "POST" }),
  algorithms: () => request<{ id: string; solver: string; family: string; label_zh: string; label_en: string; summary_zh: string; summary_en: string }[]>("/api/algorithms"),
  settings: () => request<Settings>("/api/settings"),
  saveSettings: (body: { provider: string; base_url: string; model: string; api_key?: string }) =>
    request<Settings>("/api/settings", { method: "PUT", body: JSON.stringify(body) }),
  testLlm: () => request<{ ok: boolean; message: string; message_en: string; provider: string; latency_ms?: number }>("/api/settings/test-llm", { method: "POST" }),
  llmDirectory: () => request<LlmDirectory>("/api/llm/providers"),
  saveProvider: (id: string, body: Partial<ProviderCard> & { extra_models?: ProviderCard["models"] }) =>
    request<ProviderCard>(`/api/llm/providers/${id}`, { method: "PUT", body: JSON.stringify(body) }),
  saveProviderKey: (id: string, body: { api_key: string; aws_secret?: string; aws_session?: string }) =>
    request<ProviderCard>(`/api/llm/providers/${id}/key`, { method: "POST", body: JSON.stringify(body) }),
  deleteProviderKey: (id: string) => request<ProviderCard>(`/api/llm/providers/${id}/key`, { method: "DELETE" }),
  testProvider: (id: string) => request<ProviderTestResult>(`/api/llm/providers/${id}/test`, { method: "POST" }),
  fetchProviderModels: (id: string) => request<{ models: string[]; provider: ProviderCard }>(`/api/llm/providers/${id}/models`, { method: "POST" }),
  addCustomProvider: (body: { name: string; base_url: string; protocol: string; group: string }) =>
    request<ProviderCard>("/api/llm/providers", { method: "POST", body: JSON.stringify(body) }),
  deleteCustomProvider: (id: string) => request<{ ok: boolean }>(`/api/llm/providers/${id}`, { method: "DELETE" }),
  saveLlmRoles: (roles: Record<string, RoleAssignment>) =>
    request<{ roles: Record<string, RoleAssignment>; active: LlmDirectory["active"] }>("/api/llm/roles", { method: "PUT", body: JSON.stringify({ roles }) }),
  audit: () => request<AuditRow[]>("/api/audit"),
  previewTable: (body: { filename: string; content_base64: string; encoding?: string; sheet?: string }) =>
    request<{ encoding: string; sheet: string | null; sheets: string[]; columns: string[]; rows: string[][]; row_count: number; mapping: { column: string; role: string; name: string; indexes: string[] }[] }>("/api/tables/preview", { method: "POST", body: JSON.stringify(body) }),
  applyTable: (body: { dsl: string; columns: string[]; rows: string[][]; mapping: { column: string; role: string; name: string; indexes?: string[] }[] }) =>
    request<{ ok: boolean; aml: string }>("/api/tables/apply", { method: "POST", body: JSON.stringify(body) }),
  modelData: (dsl: string) => request<{ sets: { name: string; elements: string[] }[]; parameters: { name: string; index_sets: string[]; values: { index: string[]; value: number }[] }[]; rhs: { name: string; sense: string; value: number }[] }>("/api/model-data", { method: "POST", body: JSON.stringify({ dsl }) }),
  applyModelData: (body: { dsl: string; sets?: unknown[]; parameters?: unknown[]; rhs?: { name: string; value: number }[] }) =>
    request<{ ok: boolean; aml: string }>("/api/model-data/apply", { method: "POST", body: JSON.stringify(body) }),
  recommend: (dsl: string) => request<{ solver: string; family: string; reason_zh: string; reason_en: string; algorithm?: string; label_zh?: string; label_en?: string }>("/api/recommend", { method: "POST", body: JSON.stringify({ dsl }) }),
  figures: (dsl: string) => request<{ feasible_region?: FeasibleRegion | null; pareto?: ParetoFront | null }>("/api/figures", { method: "POST", body: JSON.stringify({ dsl }) }),
  whatIfKnobs: (dsl: string) => request<{ knobs: { id: string; target: string; name: string; index: string[]; label: string; value: number; min: number; max: number }[] }>("/api/what-if/knobs", { method: "POST", body: JSON.stringify({ dsl }) }),
  whatIf: (body: { dsl: string; solver: string; changes: { target: string; name: string; index?: string[]; value: number }[] }) =>
    request<{ baseline: { status: string; objective: number | null; variables: Record<string, number> }; scenario: { status: string; objective: number | null; variables: Record<string, number> }; objective_delta: number | null }>("/api/what-if", { method: "POST", body: JSON.stringify(body) }),
  versions: (projectId: number) => request<{ id: number; label: string; dsl: string; statement: string; created_at: string }[]>(`/api/projects/${projectId}/versions`),
  saveVersion: (projectId: number, body: { label: string; dsl: string; statement: string }) =>
    request<{ id: number; label: string; dsl: string; statement: string; created_at: string }>(`/api/projects/${projectId}/versions`, { method: "POST", body: JSON.stringify(body) }),
  problems: (query = "") => request<LifeCard[]>(`/api/problems${query}`),
  problem: (id: number) => request<LifeDetail>(`/api/problems/${id}`),
  createProblem: (body: { title: string; description?: string; tags?: string[]; priority?: string; due_at?: string; custom_fields?: Record<string, string | number | boolean | null>; workspace_id?: number; project_id?: number; dsl?: string; fill_existing?: boolean }) =>
    request<LifeDetail>("/api/problems", { method: "POST", body: JSON.stringify(body) }),
  updateProblem: (id: number, body: Record<string, unknown>) => request<LifeDetail>(`/api/problems/${id}`, { method: "PATCH", body: JSON.stringify(body) }),
  deleteProblem: (id: number) => request<{ ok: boolean }>(`/api/problems/${id}`, { method: "DELETE" }),
  restoreProblem: (id: number) => request<LifeDetail>(`/api/problems/${id}/restore`, { method: "POST" }),
  purgeProblem: (id: number) => request<{ ok: boolean }>(`/api/problems/${id}/purge`, { method: "DELETE" }),
  transitionProblem: (id: number, body: { to_stage: string; comment?: string }) =>
    request<LifeDetail>(`/api/problems/${id}/transition`, { method: "POST", body: JSON.stringify(body) }),
  proposeProblem: (id: number, body: { to_stage: string; comment?: string; role?: string; actor_name?: string }) =>
    request<LifeDetail>(`/api/problems/${id}/proposals`, { method: "POST", body: JSON.stringify(body) }),
  resolveProblemRequest: (id: number, requestId: number, decision: "approved" | "rejected", comment = "") =>
    request<LifeDetail>(`/api/problems/${id}/requests/${requestId}`, { method: "POST", body: JSON.stringify({ decision, comment }) }),
  addRequirement: (id: number, text: string) => request<LifeDetail>(`/api/problems/${id}/requirements`, { method: "POST", body: JSON.stringify({ text }) }),
  suggestRequirements: (id: number) => request<LifeDetail>(`/api/problems/${id}/requirements/suggest`, { method: "POST" }),
  patchRequirement: (id: number, requirementId: number, body: { done?: boolean; text?: string }) =>
    request<LifeDetail>(`/api/problems/${id}/requirements/${requirementId}`, { method: "PATCH", body: JSON.stringify(body) }),
  addProblemData: (id: number, body: { name: string; filename?: string; content: string; note?: string; parent_id?: number }) =>
    request<LifeDetail>(`/api/problems/${id}/data`, { method: "POST", body: JSON.stringify(body) }),
  addProblemModel: (id: number, body: { aml: string; label?: string; note?: string; semver?: string }) =>
    request<LifeDetail>(`/api/problems/${id}/models`, { method: "POST", body: JSON.stringify(body) }),
  diffProblemModels: (id: number, left: number, right: number) => request<{ diff: string }>(`/api/problems/${id}/models/diff?left=${left}&right=${right}`),
  promoteBaseline: (id: number, modelId: number) => request<LifeDetail>(`/api/problems/${id}/models/${modelId}/baseline`, { method: "POST" }),
  solveProblem: (id: number, body: { solver: string; note?: string; seed?: number; aml?: string }) =>
    request<LifeDetail>(`/api/problems/${id}/runs`, { method: "POST", body: JSON.stringify(body) }),
  compareProblemRuns: (id: number, left: number, right: number) =>
    request<{ left: LifeDetail["runs"][number]; right: LifeDetail["runs"][number]; objective_delta: number | null; solution_delta: Record<string, number | null> }>(`/api/problems/${id}/runs/compare?left=${left}&right=${right}`),
  analyzeProblem: (id: number, body: { kind: string; options?: Record<string, unknown> }) =>
    request<LifeDetail>(`/api/problems/${id}/analyses`, { method: "POST", body: JSON.stringify(body) }),
  addDecision: (id: number, body: { title: string; rationale: string; rationale_en?: string; run_ids?: number[]; chosen_run_id?: number }) =>
    request<LifeDetail>(`/api/problems/${id}/decisions`, { method: "POST", body: JSON.stringify(body) }),
  writeMemo: (id: number) => request<LifeDetail>(`/api/problems/${id}/decisions/memo`, { method: "POST" }),
  acceptDecision: (id: number, decisionId: number) => request<LifeDetail>(`/api/problems/${id}/decisions/${decisionId}/accept`, { method: "POST" }),
  addChange: (id: number, body: { title: string; impact: string }) => request<LifeDetail>(`/api/problems/${id}/changes`, { method: "POST", body: JSON.stringify(body) }),
  acceptChange: (id: number, changeId: number) => request<LifeDetail>(`/api/problems/${id}/changes/${changeId}/accept`, { method: "POST" }),
  rejectChange: (id: number, changeId: number) => request<LifeDetail>(`/api/problems/${id}/changes/${changeId}/reject`, { method: "POST" }),
  makeArtifact: (id: number, kind: "pdf" | "png" | "svg" | "latex") => request<LifeDetail>(`/api/problems/${id}/artifacts`, { method: "POST", body: JSON.stringify({ kind }) }),
  problemArtifact: (id: number, artifactId: number) => request<{ id: number; kind: string; name: string; media: string; content: string }>(`/api/problems/${id}/artifacts/${artifactId}`),
  problemPackage: (id: number) => request<Record<string, unknown>>(`/api/problems/${id}/package`),
  importProblem: (payload: Record<string, unknown>) => request<LifeDetail>("/api/problems/import", { method: "POST", body: JSON.stringify({ package: payload }) }),
  problemTemplates: () => request<LifeTemplate[]>("/api/problems/templates"),
  problemFromTemplate: (templateId: string) => request<LifeDetail>("/api/problems/from-template", { method: "POST", body: JSON.stringify({ template_id: templateId }) }),
  problemNotices: () => request<LifeNotice[]>("/api/problems/notices"),
  readProblemNotices: (ids: number[]) => request<{ ok: boolean }>("/api/problems/notices/read", { method: "POST", body: JSON.stringify({ ids }) }),
  problemViews: () => request<LifeView[]>("/api/problems/views"),
  saveProblemView: (name: string, filters: Record<string, unknown>) => request<LifeView>("/api/problems/views", { method: "POST", body: JSON.stringify({ name, filters }) }),
  deleteProblemView: (id: number) => request<{ ok: boolean }>(`/api/problems/views/${id}`, { method: "DELETE" }),
  problemSummary: (id: number) => request<LifeDetail>(`/api/problems/${id}/summary`, { method: "POST" }),
  searchProblems: (q: string) => request<LifeSearch>(`/api/problems/search?q=${encodeURIComponent(q)}`),
}

export async function downloadPackage(runId: number, locale: string) {
  const headers = new Headers()
  const current = token()
  if (current) headers.set("Authorization", `Bearer ${current}`)
  const response = await fetch(`${await apiRoot()}/api/runs/${runId}/report?format=zip&locale=${encodeURIComponent(locale)}`, { headers })
  if (!response.ok) throw new ApiError("打包失败。", "The package failed.", response.status)
  const blob = await response.blob()
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement("a")
  anchor.href = url
  anchor.download = "axiom-package.zip"
  anchor.click()
  URL.revokeObjectURL(url)
}

export async function downloadReport(runId: number, format: "md" | "pdf" | "xlsx", locale: string) {
  const headers = new Headers()
  const current = token()
  if (current) headers.set("Authorization", `Bearer ${current}`)
  const response = await fetch(`${await apiRoot()}/api/runs/${runId}/report?format=${format}&locale=${encodeURIComponent(locale)}`, { headers })
  if (!response.ok) throw new ApiError("报告导出失败。", "Report export failed.", response.status)
  const blob = await response.blob()
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement("a")
  anchor.href = url
  anchor.download = `axiom-report.${format === "md" ? "md" : format}`
  anchor.click()
  URL.revokeObjectURL(url)
}

export function formatNumber(value: unknown) {
  if (value === null || value === undefined || value === "") return "—"
  const number = Number(value)
  if (!Number.isFinite(number)) return String(value)
  return new Intl.NumberFormat(undefined, { maximumFractionDigits: 4 }).format(number)
}
