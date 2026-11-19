import { useEffect, useMemo, useState, type ReactNode } from "react"
import { useTranslation } from "react-i18next"
import { toast } from "sonner"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Textarea } from "@/components/ui/textarea"
import { ApiError, api } from "@/lib/api"
import { MAIN_STAGES, SIDE_STAGES, type LifeCard, type LifeDetail, type LifeSearch, type LifeStage, type LifeTemplate, type LifeView } from "@/lib/lifecycle"
import { Sparkline } from "@/components/figures/plates"
import { useFigurePalette } from "@/components/figures/theme"
import { notifyFinished } from "@/lib/notify"

type Section = "board" | "overview" | "requirements" | "data" | "models" | "runs" | "analyses" | "decisions" | "artifacts" | "activity"

const NAV: Section[] = ["overview", "requirements", "data", "models", "runs", "analyses", "decisions", "artifacts", "activity"]

export function LifecycleBoard({
  projectId,
  section,
  onSection,
  dsl,
  onOpenProject,
}: {
  projectId: number | null
  section: string
  onSection: (section: string) => void
  dsl: string
  onOpenProject: (projectId: number) => void
}) {
  const { t, i18n } = useTranslation()
  const zh = i18n.language.startsWith("zh")
  const palette = useFigurePalette()
  const view = (NAV.includes(section as Section) ? section : "board") as Section
  const [rows, setRows] = useState<LifeCard[] | null>(null)
  const [error, setError] = useState("")
  const [mode, setMode] = useState<"kanban" | "table">("kanban")
  const [q, setQ] = useState("")
  const [appliedQ, setAppliedQ] = useState("")
  const [stage, setStage] = useState("")
  const [favoriteOnly, setFavoriteOnly] = useState(false)
  const [bin, setBin] = useState(false)
  const [sortKey, setSortKey] = useState<"updated_at" | "title" | "priority" | "best_objective" | "run_count">("updated_at")
  const [sortDir, setSortDir] = useState<1 | -1>(-1)
  const [views, setViews] = useState<LifeView[]>([])
  const [viewName, setViewName] = useState("")
  const [templates, setTemplates] = useState<LifeTemplate[]>([])
  const [showTemplates, setShowTemplates] = useState(false)
  const [showNew, setShowNew] = useState(false)
  const [draft, setDraft] = useState({ title: "", description: "", tags: "supply-chain", priority: "normal", due_at: "" })
  const [detail, setDetail] = useState<LifeDetail | null>(null)
  const [busy, setBusy] = useState(false)
  const [comment, setComment] = useState("")
  const [target, setTarget] = useState("intake")
  const [diff, setDiff] = useState("")
  const [leftModel, setLeftModel] = useState(0)
  const [rightModel, setRightModel] = useState(0)
  const [compare, setCompare] = useState<{ left: LifeDetail["runs"][number]; right: LifeDetail["runs"][number]; objective_delta: number | null } | null>(null)
  const [leftRun, setLeftRun] = useState(0)
  const [rightRun, setRightRun] = useState(0)
  const [pack, setPack] = useState("")
  const [hits, setHits] = useState<LifeSearch | null>(null)
  const [reqText, setReqText] = useState("")
  const [dataName, setDataName] = useState("")
  const [dataBody, setDataBody] = useState("")
  const [solver, setSolver] = useState("highs")
  const [study, setStudy] = useState("local")
  const [decisionTitle, setDecisionTitle] = useState("")
  const [decisionWhy, setDecisionWhy] = useState("")
  const [changeTitle, setChangeTitle] = useState("")
  const [changeImpact, setChangeImpact] = useState("")

  function fail(reason: unknown) {
    const message = reason instanceof ApiError ? (zh ? reason.message : reason.messageEn) : t("lifecycle.error")
    toast.error(message)
  }

  function announce(payload: LifeDetail) {
    const note = payload.notice
    if (note) void notifyFinished(zh ? note.title : note.title_en, zh ? note.body : note.body_en)
    window.dispatchEvent(new Event("axiom-lifecycle"))
  }

  async function loadList() {
    setError("")
    try {
      const query = new URLSearchParams()
      if (appliedQ.trim()) query.set("q", appliedQ.trim())
      if (stage) query.set("stage", stage)
      if (favoriteOnly) query.set("favorite", "1")
      if (bin) query.set("deleted", "1")
      const list = await api.problems(query.size ? `?${query.toString()}` : "")
      setRows(list)
    } catch (reason) {
      setRows([])
      setError(reason instanceof ApiError ? (zh ? reason.message : reason.messageEn) : t("lifecycle.error"))
    }
  }

  async function loadDetail(id: number) {
    const next = await api.problem(id)
    setDetail(next)
    if (next.models.length >= 2) {
      setLeftModel(next.models[0].id)
      setRightModel(next.models[next.models.length - 1].id)
    } else {
      setLeftModel(next.models[0]?.id || 0)
      setRightModel(0)
      setDiff("")
    }
    if (next.runs.length >= 2) {
      setLeftRun(next.runs[0].id)
      setRightRun(next.runs[1].id)
    } else {
      setLeftRun(next.runs[0]?.id || 0)
      setRightRun(0)
      setCompare(null)
    }
    return next
  }

  useEffect(() => {
    void loadList()
    api.problemViews().then(setViews).catch(() => setViews([]))
    api.problemTemplates().then(setTemplates).catch(() => setTemplates([]))
  }, [appliedQ, stage, favoriteOnly, bin])

  useEffect(() => {
    if (view === "board" || !projectId) return
    const match = (rows || []).find((item) => item.project_id === projectId)
    const id = match?.id || detail?.id
    if (!id) return
    loadDetail(id).catch(fail)
  }, [projectId, view, rows])

  useEffect(() => {
    if (!detail || !leftModel || !rightModel || leftModel === rightModel) {
      setDiff("")
      return
    }
    api.diffProblemModels(detail.id, leftModel, rightModel).then((payload) => setDiff(payload.diff || (zh ? "两版模型一致。" : "The two versions match."))).catch(fail)
  }, [detail?.id, leftModel, rightModel])

  useEffect(() => {
    if (!detail || !leftRun || !rightRun || leftRun === rightRun) {
      setCompare(null)
      return
    }
    api.compareProblemRuns(detail.id, leftRun, rightRun).then(setCompare).catch(fail)
  }, [detail?.id, leftRun, rightRun])

  const sorted = useMemo(() => {
    const list = [...(rows || [])]
    list.sort((a, b) => {
      const left = a[sortKey]
      const right = b[sortKey]
      if (typeof left === "number" && typeof right === "number") return (left - right) * sortDir
      return String(left ?? "").localeCompare(String(right ?? "")) * sortDir
    })
    return list
  }, [rows, sortKey, sortDir])

  const sideRows = sorted.filter((item) => SIDE_STAGES.includes(item.stage))

  async function openCard(card: LifeCard) {
    if (card.project_id) onOpenProject(card.project_id)
    onSection("overview")
    try {
      await loadDetail(card.id)
    } catch (reason) {
      fail(reason)
    }
  }

  async function mutate(work: () => Promise<LifeDetail>) {
    setBusy(true)
    try {
      const next = await work()
      setDetail(next)
      announce(next)
      await loadList()
    } catch (reason) {
      fail(reason)
    } finally {
      setBusy(false)
    }
  }

  async function createDraft() {
    await mutate(async () => {
      const created = await api.createProblem({
        title: draft.title.trim() || t("lifecycle.new"),
        description: draft.description,
        tags: draft.tags.split(/[,，\s]+/).filter(Boolean),
        priority: draft.priority,
        due_at: draft.due_at || undefined,
      })
      setShowNew(false)
      onSection("overview")
      if (created.project_id) onOpenProject(created.project_id)
      return created
    })
  }

  function stageLabel(name: string) {
    return t(`lifecycle.stage.${name}`, { defaultValue: name })
  }

  function summaryText(item: { ai_summary: string; ai_summary_en: string; next_action: string; next_action_en: string }) {
    return zh ? item.ai_summary : item.ai_summary_en
  }

  return (
    <div className="flex h-full min-h-[520px] flex-col text-[13px]" data-lifecycle-root>
      <div className="flex flex-wrap items-center gap-1 border-b px-2 py-1">
        <Button size="sm" variant={view === "board" ? "default" : "outline"} onClick={() => onSection("board")}>{t("lifecycle.board")}</Button>
        {detail ? NAV.map((item) => (
          <Button key={item} size="sm" variant={view === item ? "default" : "outline"} onClick={() => onSection(item)}>{t(`lifecycle.nav.${item}`)}</Button>
        )) : null}
        <span className="ml-auto text-[11px] text-muted-foreground">{t("lifecycle.lead")}</span>
      </div>
      {view === "board" ? (
        <div className="flex min-h-0 flex-1 flex-col">
          <div className="flex flex-wrap items-center gap-1 border-b px-2 py-1">
            <Input className="h-7 w-56 text-xs" value={q} placeholder={t("lifecycle.search")} onChange={(event) => setQ(event.target.value)} onKeyDown={(event) => { if (event.key === "Enter") { setAppliedQ(q); void api.searchProblems(q).then(setHits).catch(fail) } }} />
            <Button size="sm" variant={mode === "kanban" ? "default" : "outline"} onClick={() => setMode("kanban")}>{t("lifecycle.board")}</Button>
            <Button size="sm" variant={mode === "table" ? "default" : "outline"} onClick={() => setMode("table")}>{t("lifecycle.table")}</Button>
            <Button size="sm" variant={favoriteOnly ? "default" : "outline"} onClick={() => setFavoriteOnly((value) => !value)}>{t("lifecycle.favorite")}</Button>
            <Button size="sm" variant={bin ? "default" : "outline"} onClick={() => setBin((value) => !value)}>{t("lifecycle.recycle")}</Button>
            <Button size="sm" variant="outline" onClick={() => setShowNew((value) => !value)}>{t("lifecycle.new")}</Button>
            <Button size="sm" variant="outline" onClick={() => setShowTemplates((value) => !value)}>{t("lifecycle.fromTemplate")}</Button>
            <label className="cursor-pointer">
              <input type="file" accept="application/json,.json" className="hidden" onChange={(event) => {
                const file = event.target.files?.[0]
                event.target.value = ""
                if (!file) return
                void file.text().then((text) => api.importProblem(JSON.parse(text) as Record<string, unknown>)).then((created) => {
                  toast.success(created.title)
                  if (created.project_id) onOpenProject(created.project_id)
                  onSection("overview")
                  setDetail(created)
                  return loadList()
                }).catch(fail)
              }} />
              <span className="inline-flex h-7 items-center border px-2 text-xs">{t("lifecycle.import")}</span>
            </label>
            <Input className="h-7 w-28 text-xs" value={viewName} placeholder={t("lifecycle.viewName")} onChange={(event) => setViewName(event.target.value)} />
            <Button size="sm" variant="outline" onClick={() => void api.saveProblemView(viewName || t("lifecycle.saved"), { q, stage, favoriteOnly, bin, mode }).then((saved) => setViews((current) => [saved, ...current])).catch(fail)}>{t("lifecycle.saveView")}</Button>
            {views.map((item) => (
              <Button key={item.id} size="sm" variant="outline" onClick={() => {
                const filters = item.filters || {}
                setQ(String(filters.q || "")); setAppliedQ(String(filters.q || ""))
                setStage(String(filters.stage || ""))
                setFavoriteOnly(Boolean(filters.favoriteOnly))
                setBin(Boolean(filters.bin))
                if (filters.mode === "table" || filters.mode === "kanban") setMode(filters.mode)
              }}>{item.name}</Button>
            ))}
          </div>
          <div className="flex flex-wrap gap-1 border-b px-2 py-1">
            <Button size="sm" variant={stage === "" ? "default" : "outline"} onClick={() => setStage("")}>{t("lifecycle.all")}</Button>
            {[...MAIN_STAGES, ...SIDE_STAGES].map((item) => (
              <Button key={item} size="sm" variant={stage === item ? "default" : "outline"} onClick={() => setStage(item)}>{stageLabel(item)}</Button>
            ))}
          </div>
          {showNew ? (
            <form className="grid gap-1 border-b p-2 sm:grid-cols-2" onSubmit={(event) => { event.preventDefault(); void createDraft() }}>
              <Input className="h-7 text-xs" value={draft.title} placeholder={t("lifecycle.title")} onChange={(event) => setDraft({ ...draft, title: event.target.value })} />
              <Input className="h-7 text-xs" type="date" value={draft.due_at} aria-label={t("lifecycle.due")} onChange={(event) => setDraft({ ...draft, due_at: event.target.value })} />
              <Textarea className="min-h-16 text-xs sm:col-span-2" value={draft.description} placeholder={t("lifecycle.description")} onChange={(event) => setDraft({ ...draft, description: event.target.value })} />
              <Input className="h-7 text-xs" value={draft.tags} placeholder={t("lifecycle.tags")} onChange={(event) => setDraft({ ...draft, tags: event.target.value })} />
              <select className="h-7 border bg-background px-1 text-xs" aria-label={t("lifecycle.priority")} value={draft.priority} onChange={(event) => setDraft({ ...draft, priority: event.target.value })}>
                {["low", "normal", "high", "urgent"].map((item) => <option key={item} value={item}>{t(`lifecycle.priorityLevel.${item}`)}</option>)}
              </select>
              <div className="flex gap-1">
                <Button size="sm" type="submit" disabled={busy}>{t("lifecycle.create")}</Button>
                <Button size="sm" type="button" variant="outline" onClick={() => setShowNew(false)}>{t("lifecycle.cancel")}</Button>
              </div>
            </form>
          ) : null}
          {showTemplates ? (
            <div className="grid gap-1 border-b p-2 sm:grid-cols-2">
              {templates.map((item) => (
                <button key={item.id} type="button" className="border px-2 py-1 text-left hover:bg-muted" onClick={() => void mutate(async () => {
                  const created = await api.problemFromTemplate(item.id)
                  setShowTemplates(false)
                  onSection("overview")
                  if (created.project_id) onOpenProject(created.project_id)
                  return created
                })}>
                  <div className="font-medium">{zh ? item.title_zh : item.title_en}</div>
                  <div className="text-[11px] text-muted-foreground">{zh ? item.summary_zh : item.summary_en}</div>
                </button>
              ))}
            </div>
          ) : null}
          {hits ? (
            <div className="border-b px-2 py-1 text-xs">
              <div className="mb-1 flex items-center gap-2 font-medium">{t("lifecycle.hits")}<Button size="sm" variant="outline" onClick={() => setHits(null)}>{t("lifecycle.close")}</Button></div>
              {hits.problems.length + hits.models.length + hits.runs.length === 0 ? <p>{t("lifecycle.noHits")}</p> : null}
              {hits.problems.map((item) => <button key={`p${item.id}`} type="button" className="block w-full truncate text-left hover:bg-muted" onClick={() => { const card = (rows || []).find((row) => row.id === item.id); if (card) void openCard(card) }}>{t("lifecycle.problemsHit")} · {item.title}</button>)}
              {hits.models.map((item) => <div key={`m${item.id}`} className="truncate text-muted-foreground">{t("lifecycle.modelsHit")} {item.semver} · {item.snippet}</div>)}
              {hits.runs.map((item) => <div key={`r${item.id}`} className="truncate text-muted-foreground">{t("lifecycle.runsHit")} {item.solver} · {item.snippet}</div>)}
            </div>
          ) : null}
          {rows === null ? <div className="app-skeleton m-2" data-loading="lifecycle" /> : null}
          {error ? <div className="p-3"><p className="text-destructive">{error}</p><Button size="sm" className="mt-2" onClick={() => void loadList()}>{t("lifecycle.retry")}</Button></div> : null}
          {rows !== null && rows.length === 0 && !error ? <p className="p-4 text-muted-foreground">{t("lifecycle.empty")}</p> : null}
          {mode === "kanban" && rows !== null && rows.length > 0 ? (
            <div className="flex min-h-0 flex-1 gap-2 overflow-auto p-2" data-lifecycle-board>
              {(stage && SIDE_STAGES.includes(stage as LifeStage) ? [stage as LifeStage] : MAIN_STAGES).map((column) => (
                <div key={column} className="w-44 shrink-0">
                  <div className="mb-1 flex items-center justify-between text-[11px] text-muted-foreground">
                    <span>{stageLabel(column)}</span>
                    <span>{sorted.filter((item) => item.stage === column).length}</span>
                  </div>
                  <div className="space-y-1">
                    {sorted.filter((item) => item.stage === column).map((card) => (
                      <CardButton key={card.id} card={card} zh={zh} label={stageLabel(card.stage)} onClick={() => void openCard(card)} />
                    ))}
                  </div>
                </div>
              ))}
              {!stage && sideRows.length ? (
                <div className="w-44 shrink-0">
                  <div className="mb-1 text-[11px] text-muted-foreground">{t("lifecycle.side")}</div>
                  {sideRows.map((card) => <CardButton key={card.id} card={card} zh={zh} label={stageLabel(card.stage)} onClick={() => void openCard(card)} />)}
                </div>
              ) : null}
            </div>
          ) : null}
          {mode === "table" && rows !== null && rows.length > 0 ? (
            <div className="min-h-0 flex-1 overflow-auto" data-lifecycle-board>
              <table className="w-full text-left text-xs">
                <thead>
                  <tr className="border-b">
                    {(["title", "stage", "priority", "best_objective", "run_count", "updated_at"] as const).map((key) => (
                      <th key={key} className="px-2 py-1 font-medium">
                        <button type="button" onClick={() => { setSortKey(key === "stage" ? "title" : key); setSortDir((dir) => (dir === 1 ? -1 : 1)) }}>
                          {key === "title" ? t("lifecycle.title") : key === "stage" ? t("lifecycle.status") : key === "priority" ? t("lifecycle.priority") : key === "best_objective" ? t("lifecycle.best") : key === "run_count" ? t("lifecycle.runs") : t("lifecycle.last")}
                        </button>
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {sorted.map((card) => (
                    <tr key={card.id} className="cursor-pointer border-b hover:bg-muted" onClick={() => void openCard(card)}>
                      <td className="px-2 py-1">{card.title}</td>
                      <td className="px-2 py-1">{stageLabel(card.stage)}</td>
                      <td className="px-2 py-1">{t(`lifecycle.priorityLevel.${card.priority}`, { defaultValue: card.priority })}</td>
                      <td className="px-2 py-1">{card.best_objective ?? "—"}</td>
                      <td className="px-2 py-1">{card.run_count}</td>
                      <td className="px-2 py-1">{card.last_activity?.slice(0, 16) || "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : null}
        </div>
      ) : detail ? (
        <div className="min-h-0 flex-1 overflow-auto p-3">
          <div className="mb-2 flex flex-wrap items-center gap-2">
            <h2 className="text-sm font-medium">{detail.title}</h2>
            <Badge variant="secondary">{stageLabel(detail.stage)}</Badge>
            <Badge variant="outline">{t(`lifecycle.roleName.${detail.role}`, { defaultValue: detail.role })}</Badge>
            {detail.deleted_at ? <Badge variant="destructive">{t("lifecycle.softDeleted")}</Badge> : null}
            <Button size="sm" variant="outline" onClick={() => void mutate(() => api.updateProblem(detail.id, { favorite: !detail.favorite }))}>{detail.favorite ? "★" : "☆"} {t("lifecycle.favorite")}</Button>
            {detail.deleted_at ? <Button size="sm" variant="outline" onClick={() => void mutate(() => api.restoreProblem(detail.id))}>{t("lifecycle.restore")}</Button> : <Button size="sm" variant="outline" onClick={() => void mutate(async () => { await api.deleteProblem(detail.id); onSection("board"); return detail })}>{t("lifecycle.recycle")}</Button>}
            <Button size="sm" variant="outline" disabled={detail.role !== "owner" || !detail.deleted_at} title={t("lifecycle.permanent")} onClick={() => void api.purgeProblem(detail.id).then(() => { onSection("board"); setDetail(null); return loadList() }).catch(fail)}>{t("lifecycle.purge")}</Button>
          </div>
          {view === "overview" ? (
            <div data-lifecycle-overview className="space-y-3">
              <ol className="flex gap-1 overflow-auto" data-lifecycle-stepper>
                {MAIN_STAGES.map((item, index) => {
                  const here = MAIN_STAGES.indexOf(detail.stage as LifeStage)
                  const on = item === detail.stage
                  return (
                    <li key={item} className={`min-w-16 border px-2 py-1 text-center text-[11px] ${on ? "border-primary bg-primary text-primary-foreground" : here > index ? "bg-muted" : ""}`}>
                      <div>{index + 1}</div>
                      <div>{stageLabel(item)}</div>
                    </li>
                  )
                })}
              </ol>
              {SIDE_STAGES.includes(detail.stage as LifeStage) ? <p className="text-xs">{stageLabel(detail.stage)}{detail.resume_stage ? ` → ${stageLabel(detail.resume_stage)}` : ""}</p> : null}
              <div className="grid gap-2 sm:grid-cols-3">
                <Kpi label={t("lifecycle.best")} value={detail.best_objective ?? "—"} extra={<Sparkline palette={palette} values={detail.runs.map((item) => item.objective).filter((value): value is number => value != null).slice().reverse()} />} />
                <Kpi label={t("lifecycle.runs")} value={detail.run_count} />
                <Kpi label={t("lifecycle.last")} value={detail.last_activity?.slice(0, 16) || "—"} />
              </div>
              {detail.models.length > 1 && detail.runs.some((item) => item.objective != null) ? (
                <div data-lifecycle-trend>
                  <div className="mb-1 text-[11px] text-muted-foreground">{zh ? "目标随模型版本" : "Objective across model versions"}</div>
                  <Sparkline palette={palette} width={280} height={42} values={detail.models.map((model) => {
                    const related = detail.runs.filter((item) => item.model_revision_id === model.id && item.objective != null)
                    if (!related.length) return Number.NaN
                    return Math.max(...related.map((item) => item.objective || 0))
                  }).filter((value) => Number.isFinite(value))} />
                </div>
              ) : null}
              <section>
                <div className="mb-1 flex items-center gap-2 font-medium">{t("lifecycle.summary")}<Button size="sm" variant="outline" onClick={() => void mutate(() => api.problemSummary(detail.id))}>{t("lifecycle.refresh")}</Button></div>
                <p>{summaryText(detail)}</p>
              </section>
              <div className="flex flex-wrap gap-1">
                <Button size="sm" disabled={busy || !detail.next_stage} onClick={() => void mutate(() => api.transitionProblem(detail.id, { to_stage: detail.next_stage || "", comment }))}>{zh ? detail.next_action : detail.next_action_en}</Button>
                <Button size="sm" variant="outline" onClick={() => void mutate(() => api.transitionProblem(detail.id, { to_stage: "on_hold", comment }))}>{t("lifecycle.hold")}</Button>
                <Button size="sm" variant="outline" onClick={() => void mutate(() => api.transitionProblem(detail.id, { to_stage: "blocked", comment }))}>{t("lifecycle.block")}</Button>
              </div>
              <div className="flex flex-wrap items-center gap-1">
                <select className="h-7 border bg-background px-1 text-xs" aria-label={t("lifecycle.transition")} value={target} onChange={(event) => setTarget(event.target.value)}>
                  {[...MAIN_STAGES, ...SIDE_STAGES].map((item) => <option key={item} value={item}>{stageLabel(item)}</option>)}
                </select>
                <Input className="h-7 w-56 text-xs" value={comment} placeholder={t("lifecycle.comment")} onChange={(event) => setComment(event.target.value)} />
                <Button size="sm" variant="outline" disabled={busy} onClick={() => void mutate(() => api.transitionProblem(detail.id, { to_stage: target, comment }))}>{t("lifecycle.transition")}</Button>
              </div>
              <label className="flex items-center gap-2 text-xs"><input type="checkbox" checked={detail.auto_advance} onChange={(event) => void mutate(() => api.updateProblem(detail.id, { auto_advance: event.target.checked }))} />{t("lifecycle.auto")}</label>
              <label className="flex items-center gap-2 text-xs"><input type="checkbox" checked={detail.approval_required} onChange={(event) => void mutate(() => api.updateProblem(detail.id, { approval_required: event.target.checked }))} />{t("lifecycle.approval")}</label>
              {detail.requests.map((item) => (
                <div key={item.id} className="flex flex-wrap items-center gap-2 border px-2 py-1">
                  <span>{t("lifecycle.pending")} · {item.actor_name}: {stageLabel(item.from_stage)} → {stageLabel(item.to_stage)}</span>
                  <Button size="sm" onClick={() => void mutate(() => api.resolveProblemRequest(detail.id, item.id, "approved", comment))}>{t("lifecycle.approve")}</Button>
                  <Button size="sm" variant="outline" onClick={() => void mutate(() => api.resolveProblemRequest(detail.id, item.id, "rejected", comment))}>{t("lifecycle.rejectRequest")}</Button>
                </div>
              ))}
              <p className="text-[11px] text-muted-foreground">{detail.tags.map((tag) => t(`lifecycle.domain.${tag}`, { defaultValue: tag })).join(" · ")} {detail.due_at ? `· ${t("lifecycle.due")} ${detail.due_at.slice(0, 10)}` : ""} · {t("lifecycle.owner")} {detail.owner_name}</p>
            </div>
          ) : null}
          {view === "requirements" ? (
            <div className="space-y-2">
              <div className="flex gap-1">
                <Button size="sm" onClick={() => void mutate(() => api.suggestRequirements(detail.id))}>{t("lifecycle.suggest")}</Button>
              </div>
              {detail.requirements.map((item) => (
                <label key={item.id} className="flex items-start gap-2 border px-2 py-1">
                  <input type="checkbox" checked={item.done} onChange={(event) => void mutate(() => api.patchRequirement(detail.id, item.id, { done: event.target.checked }))} />
                  <span><span className={item.done ? "line-through" : ""}>{zh ? item.text : item.text_en || item.text}</span><span className="ml-2 text-[11px] text-muted-foreground">{item.source}</span></span>
                </label>
              ))}
              <form className="flex gap-1" onSubmit={(event) => { event.preventDefault(); if (!reqText.trim()) return; void mutate(() => api.addRequirement(detail.id, reqText.trim())).then(() => setReqText("")) }}>
                <Input className="h-7 text-xs" value={reqText} placeholder={t("lifecycle.requirements")} onChange={(event) => setReqText(event.target.value)} />
                <Button size="sm" type="submit">{t("lifecycle.add")}</Button>
              </form>
            </div>
          ) : null}
          {view === "data" ? (
            <div className="space-y-2">
              {detail.data.map((item) => (
                <article key={item.id} className="border px-2 py-1">
                  <div className="font-medium">{item.name} · v{item.version}</div>
                  <div className="text-[11px] text-muted-foreground">{t("lifecycle.schema")}: {item.schema.map((column) => column.name).join(", ") || "—"} {item.parent_id ? `· ${t("lifecycle.lineage")} #${item.parent_id}` : ""}</div>
                  <pre className="mt-1 max-h-24 overflow-auto text-[11px]">{item.content}</pre>
                </article>
              ))}
              <form className="space-y-1" onSubmit={(event) => { event.preventDefault(); void mutate(() => api.addProblemData(detail.id, { name: dataName || "data.csv", filename: `${dataName || "data"}.csv`, content: dataBody })) }}>
                <Input className="h-7 text-xs" value={dataName} placeholder={t("lifecycle.dataAsset")} onChange={(event) => setDataName(event.target.value)} />
                <Textarea className="min-h-16 font-mono text-xs" value={dataBody} placeholder={"name,value\nA,1"} onChange={(event) => setDataBody(event.target.value)} />
                <Button size="sm" type="submit">{t("lifecycle.add")}</Button>
              </form>
            </div>
          ) : null}
          {view === "models" ? (
            <div className="space-y-2" data-model-diff>
              <div className="flex flex-wrap gap-1">
                <Button size="sm" onClick={() => void mutate(() => api.addProblemModel(detail.id, { aml: dsl, label: zh ? "编辑器" : "Editor" }))}>{t("lifecycle.add")}</Button>
              </div>
              {detail.models.map((item) => (
                <div key={item.id} className="flex flex-wrap items-center gap-2 border px-2 py-1">
                  <span className="font-medium">{item.semver}</span>
                  <span>{item.label}</span>
                  {item.baseline ? <Badge>{t("lifecycle.baseline")}</Badge> : <Button size="sm" variant="outline" onClick={() => void mutate(() => api.promoteBaseline(detail.id, item.id))}>{t("lifecycle.promote")}</Button>}
                </div>
              ))}
              <div className="flex flex-wrap gap-1">
                <select className="h-7 border bg-background px-1 text-xs" aria-label="left" value={leftModel} onChange={(event) => setLeftModel(Number(event.target.value))}>
                  {detail.models.map((item) => <option key={item.id} value={item.id}>{item.semver}</option>)}
                </select>
                <select className="h-7 border bg-background px-1 text-xs" aria-label="right" value={rightModel} onChange={(event) => setRightModel(Number(event.target.value))}>
                  {detail.models.map((item) => <option key={item.id} value={item.id}>{item.semver}</option>)}
                </select>
              </div>
              <pre className="max-h-80 overflow-auto border p-2 font-mono text-[11px] whitespace-pre-wrap">{diff || t("lifecycle.diff")}</pre>
              {detail.models[0]?.latex ? <pre className="overflow-auto border p-2 text-[11px] whitespace-pre-wrap">{detail.models.find((item) => item.baseline)?.latex || detail.models[0].latex}</pre> : null}
            </div>
          ) : null}
          {view === "runs" ? (
            <div className="space-y-2" data-run-compare>
              <form className="flex flex-wrap gap-1" onSubmit={(event) => { event.preventDefault(); void mutate(() => api.solveProblem(detail.id, { solver, note: comment, aml: dsl })) }}>
                <select className="h-7 border bg-background px-1 text-xs" aria-label={t("lifecycle.solver")} value={solver} onChange={(event) => setSolver(event.target.value)}>
                  {["highs", "scip", "cbc", "glpk"].map((item) => <option key={item} value={item}>{item}</option>)}
                </select>
                <Button size="sm" type="submit" disabled={busy}>{t("lifecycle.runSolve")}</Button>
              </form>
              {detail.runs.length === 0 ? <p className="text-muted-foreground">{t("lifecycle.noRuns")}</p> : null}
              <table className="w-full text-left text-xs">
                <thead><tr className="border-b"><th className="py-1">{t("lifecycle.solver")}</th><th>{t("lifecycle.status")}</th><th>{t("lifecycle.objective")}</th><th>{t("lifecycle.wall")}</th></tr></thead>
                <tbody>
                  {detail.runs.map((item) => (
                    <tr key={item.id} className="border-b">
                      <td className="py-1">{item.solver}</td>
                      <td>{item.status}</td>
                      <td>{item.objective ?? "—"}</td>
                      <td>{item.wall_ms} ms</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <div className="flex flex-wrap gap-1">
                <select className="h-7 border bg-background px-1 text-xs" aria-label="run-left" value={leftRun} onChange={(event) => setLeftRun(Number(event.target.value))}>
                  {detail.runs.map((item) => <option key={item.id} value={item.id}>{item.solver} #{item.id}</option>)}
                </select>
                <select className="h-7 border bg-background px-1 text-xs" aria-label="run-right" value={rightRun} onChange={(event) => setRightRun(Number(event.target.value))}>
                  {detail.runs.map((item) => <option key={item.id} value={item.id}>{item.solver} #{item.id}</option>)}
                </select>
              </div>
              {compare ? (
                <div className="grid gap-2 sm:grid-cols-2">
                  <RunColumn title={`${compare.left.solver} ${compare.left.objective ?? "—"}`} run={compare.left} />
                  <RunColumn title={`${compare.right.solver} ${compare.right.objective ?? "—"}`} run={compare.right} />
                  <p className="text-xs sm:col-span-2">{t("lifecycle.objective")} Δ {compare.objective_delta ?? "—"}</p>
                </div>
              ) : null}
            </div>
          ) : null}
          {view === "analyses" ? (
            <div className="space-y-2">
              <form className="flex gap-1" onSubmit={(event) => { event.preventDefault(); void mutate(() => api.analyzeProblem(detail.id, { kind: study, options: { samples: 8 } })) }}>
                <select className="h-7 border bg-background px-1 text-xs" aria-label={t("lifecycle.study")} value={study} onChange={(event) => setStudy(event.target.value)}>
                  {["local", "doe", "sobol", "uq", "sweep", "morris"].map((item) => <option key={item} value={item}>{item}</option>)}
                </select>
                <Button size="sm" type="submit" disabled={busy}>{t("lifecycle.runStudy")}</Button>
              </form>
              {detail.analyses.map((item) => (
                <article key={item.id} className="border px-2 py-1">
                  <div className="font-medium">{item.kind} · {item.status}</div>
                  <pre className="max-h-28 overflow-auto text-[11px]">{JSON.stringify(item.result?.summary_metrics || item.result?.message || item.note || item.result, null, 2)}</pre>
                </article>
              ))}
            </div>
          ) : null}
          {view === "decisions" ? (
            <div className="space-y-2">
              <Button size="sm" onClick={() => void mutate(() => api.writeMemo(detail.id))}>{t("lifecycle.memo")}</Button>
              {detail.decisions.map((item) => (
                <article key={item.id} className="border px-2 py-1">
                  <div className="font-medium">{item.title} · {item.status}</div>
                  <p className="text-xs">{zh ? item.rationale : item.rationale_en || item.rationale}</p>
                  {item.status === "proposed" ? <Button size="sm" className="mt-1" onClick={() => void mutate(() => api.acceptDecision(detail.id, item.id))}>{t("lifecycle.acceptDecision")}</Button> : null}
                </article>
              ))}
              <form className="space-y-1" onSubmit={(event) => { event.preventDefault(); void mutate(() => api.addDecision(detail.id, { title: decisionTitle, rationale: decisionWhy, run_ids: detail.runs.map((item) => item.id) })) }}>
                <Input className="h-7 text-xs" value={decisionTitle} placeholder={t("lifecycle.decision")} onChange={(event) => setDecisionTitle(event.target.value)} />
                <Textarea className="min-h-16 text-xs" value={decisionWhy} placeholder={t("lifecycle.rationale")} onChange={(event) => setDecisionWhy(event.target.value)} />
                <Button size="sm" type="submit">{t("lifecycle.add")}</Button>
              </form>
              <h3 className="pt-2 font-medium">{t("lifecycle.change")}</h3>
              {detail.changes.map((item) => (
                <article key={item.id} className="border px-2 py-1">
                  <div className="font-medium">{item.title} · {item.status}</div>
                  <p className="text-xs">{item.impact}</p>
                  {item.status === "open" ? (
                    <div className="mt-1 flex gap-1">
                      <Button size="sm" onClick={() => void mutate(() => api.acceptChange(detail.id, item.id))}>{t("lifecycle.approve")}</Button>
                      <Button size="sm" variant="outline" onClick={() => void mutate(() => api.rejectChange(detail.id, item.id))}>{t("lifecycle.rejectRequest")}</Button>
                    </div>
                  ) : null}
                </article>
              ))}
              <form className="space-y-1" onSubmit={(event) => { event.preventDefault(); void mutate(() => api.addChange(detail.id, { title: changeTitle, impact: changeImpact })) }}>
                <Input className="h-7 text-xs" value={changeTitle} placeholder={t("lifecycle.change")} onChange={(event) => setChangeTitle(event.target.value)} />
                <Textarea className="min-h-16 text-xs" value={changeImpact} placeholder={t("lifecycle.impact")} onChange={(event) => setChangeImpact(event.target.value)} />
                <Button size="sm" type="submit">{t("lifecycle.add")}</Button>
              </form>
            </div>
          ) : null}
          {view === "artifacts" ? (
            <div className="space-y-2">
              <div className="flex flex-wrap gap-1">
                <Button size="sm" onClick={() => void mutate(() => api.makeArtifact(detail.id, "pdf"))}>{t("lifecycle.report")}</Button>
                <Button size="sm" variant="outline" onClick={() => void mutate(() => api.makeArtifact(detail.id, "svg"))}>SVG</Button>
                <Button size="sm" variant="outline" onClick={() => void mutate(() => api.makeArtifact(detail.id, "png"))}>PNG</Button>
                <Button size="sm" variant="outline" onClick={() => void mutate(() => api.makeArtifact(detail.id, "latex"))}>{t("lifecycle.latex")}</Button>
                <Button size="sm" variant="outline" data-share-export onClick={() => void api.problemPackage(detail.id).then((payload) => {
                  setPack(JSON.stringify(payload, null, 2))
                  const blob = new Blob([JSON.stringify(payload, null, 2)], { type: "application/json" })
                  const url = URL.createObjectURL(blob)
                  const anchor = document.createElement("a")
                  anchor.href = url
                  anchor.download = `${detail.title}.axiom-problem.json`
                  anchor.click()
                  URL.revokeObjectURL(url)
                }).catch(fail)}>{t("lifecycle.export")}</Button>
              </div>
              {detail.artifacts.map((item) => (
                <div key={item.id} className="border px-2 py-1">
                  <div>{item.name} · {item.kind}</div>
                  {item.kind === "svg" && item.content ? <img alt={item.name} className="max-h-28" src={`data:image/svg+xml;charset=utf-8,${encodeURIComponent(item.content)}`} /> : null}
                  {item.kind === "latex" && item.content ? <pre className="overflow-auto text-[11px]">{item.content}</pre> : null}
                </div>
              ))}
              {pack ? <pre className="max-h-64 overflow-auto border p-2 text-[11px]" data-share-export>{pack.slice(0, 4000)}</pre> : null}
            </div>
          ) : null}
          {view === "activity" ? (
            <ol className="space-y-2" data-lifecycle-activity>
              {detail.activities.length === 0 ? <li>{t("lifecycle.activityEmpty")}</li> : null}
              {detail.activities.map((item) => (
                <li key={item.id} className="border-l-2 border-primary pl-2">
                  <div className="text-[11px] text-muted-foreground">{item.created_at?.replace("T", " ").slice(0, 19)} · {item.actor_name} · {item.actor_kind}</div>
                  <div>{zh ? item.detail : item.detail_en || item.detail}</div>
                </li>
              ))}
              {detail.transitions.length ? (
                <li className="pt-2 text-[11px] text-muted-foreground">
                  {detail.transitions.map((item) => `${stageLabel(item.from_stage)}→${stageLabel(item.to_stage)} ${item.actor_name}`).join(" · ")}
                </li>
              ) : null}
            </ol>
          ) : null}
        </div>
      ) : (
        rows === null ? <div className="app-skeleton m-2" data-loading="lifecycle" /> : <div className="p-4 text-muted-foreground">{t("lifecycle.empty")}</div>
      )}
    </div>
  )
}

function CardButton({ card, zh, label, onClick }: { card: LifeCard; zh: boolean; label: string; onClick: () => void }) {
  return (
    <button type="button" data-problem-id={card.id} className="mb-1 block w-full border bg-card px-2 py-1 text-left hover:bg-muted" onClick={onClick}>
      <div className="truncate font-medium">{card.title}</div>
      <div className="mt-1 flex flex-wrap gap-1 text-[10px] text-muted-foreground">
        <span>{label}</span>
        {card.favorite ? <span>★</span> : null}
        <span>{card.best_objective ?? "—"}</span>
      </div>
      <div className="truncate text-[10px] text-muted-foreground">{zh ? card.ai_summary : card.ai_summary_en}</div>
    </button>
  )
}

function Kpi({ label, value, extra }: { label: string; value: string | number; extra?: ReactNode }) {
  return (
    <div className="border px-2 py-1">
      <div className="text-[11px] text-muted-foreground">{label}</div>
      <div className="font-medium">{value}</div>
      {extra}
    </div>
  )
}

function RunColumn({ title, run }: { title: string; run: LifeDetail["runs"][number] }) {
  const { t } = useTranslation()
  return (
    <div className="border p-2 text-xs">
      <div className="font-medium">{title}</div>
      <div>{t("lifecycle.status")} {run.status}</div>
      <div>{t("lifecycle.wall")} {run.wall_ms} ms</div>
      <pre className="mt-1 max-h-40 overflow-auto">{JSON.stringify(run.solution, null, 2)}</pre>
      {Object.keys(run.duals || {}).length ? <pre className="max-h-24 overflow-auto">{JSON.stringify(run.duals, null, 2)}</pre> : null}
    </div>
  )
}
