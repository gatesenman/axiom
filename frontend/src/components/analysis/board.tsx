import { useEffect, useMemo, useState, type ReactNode } from "react"
import { useTranslation } from "react-i18next"
import { ApiError, api } from "@/lib/api"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import {
  DistributionChart,
  EffectsChart,
  Heatmap,
  HistoryChart,
  MatrixChart,
  MorrisChart,
  N2Chart,
  ParallelChart,
  ParetoChart,
  ScheduleChart,
  SobolChart,
  SurfaceChart,
  TornadoChart,
} from "@/components/analysis/charts"
import type { AnalysisJob, AnalysisProposal, Study, StudyPoint } from "@/components/analysis/types"

type Saved = { id: string; kind: string; at: string; study: Study }

const WIZARDS = ["doe", "sensitivity", "uq", "mdo", "multi", "more"] as const

export function AnalysisBoard({
  dsl,
  solver,
  projectId,
  focus,
  seed,
  proposals,
}: {
  dsl: string
  solver: string
  projectId?: string
  focus?: string
  seed?: { token: number; study: Study } | null
  proposals?: AnalysisProposal[]
}) {
  const { t, i18n } = useTranslation()
  const zh = i18n.language.startsWith("zh")
  const [wizard, setWizard] = useState<(typeof WIZARDS)[number]>("mdo")
  const [method, setMethod] = useState("lhs")
  const [surrogate, setSurrogate] = useState("polynomial")
  const [samples, setSamples] = useState("16")
  const [mode, setMode] = useState("local")
  const [template, setTemplate] = useState("sellar")
  const [architecture, setArchitecture] = useState("mdf")
  const [mda, setMda] = useState("gauss-seidel")
  const [multi, setMulti] = useState("nsga2")
  const [job, setJob] = useState<AnalysisJob | null>(null)
  const [error, setError] = useState("")
  const [history, setHistory] = useState<Saved[]>([])
  const [activeId, setActiveId] = useState<string | null>(null)
  const [compareId, setCompareId] = useState<string | null>(null)
  const [selected, setSelected] = useState<string | null>(null)
  const [pinned, setPinned] = useState<string | null>(null)
  const [coupling, setCoupling] = useState<{ from: string; to: string; variables: string[] } | null>(null)
  const [zoom, setZoom] = useState(1)

  useEffect(() => {
    if (wizard === "uq" && mode !== "monte-carlo" && mode !== "lhs" && mode !== "form") setMode("monte-carlo")
    if (wizard === "sensitivity" && mode !== "local" && mode !== "morris" && mode !== "sobol") setMode("local")
    if (wizard === "more" && !["sweep", "robust", "chance", "iis", "quality", "schedule"].includes(mode)) setMode("sweep")
  }, [wizard, mode])

  useEffect(() => {
    const next = focusToWizard(focus)
    if (next) setWizard(next)
    if (focus === "morris" || focus === "sobol" || focus === "local") setMode(focus)
    if (focus === "doe" || focus === "sweep" || focus === "robust" || focus === "chance" || focus === "iis" || focus === "schedule" || focus === "form") setMode(focus)
  }, [focus])

  useEffect(() => {
    if (!seed) return
    const saved = { id: `chat-${seed.token}`, kind: seed.study.kind || "study", at: new Date().toISOString(), study: seed.study }
    setHistory((current) => [saved, ...current.filter((item) => item.id !== saved.id)])
    setActiveId(saved.id)
    setSelected(null)
  }, [seed])

  useEffect(() => {
    if (!projectId) return
    let stop = false
    api.runs(Number(projectId)).then((rows) => {
      if (stop) return
      const saved = rows.flatMap((row) => {
        const payload = row.result as { study?: Study; job?: string } | undefined
        const study = payload?.study
        if (row.solver !== "analysis" || !study || typeof study !== "object") return []
        return [{ id: payload?.job || `run-${row.id}`, kind: study.kind || row.statement || "analysis", at: row.created_at, study }]
      })
      if (saved.length) {
        setHistory((current) => {
          const ids = new Set(current.map((item) => item.id))
          return [...current, ...saved.filter((item) => !ids.has(item.id))]
        })
      }
    }).catch(() => undefined)
    return () => { stop = true }
  }, [projectId, job?.status])

  useEffect(() => {
    if (!job || (job.status !== "running" && job.status !== "queued")) return
    const timer = window.setInterval(() => {
      api.analysisJob(job.id).then((next) => {
        setJob(next)
        if (next.status === "running" || next.status === "queued") return
        adopt(next)
      }).catch((reason) => setError(reason instanceof ApiError ? (zh ? reason.message : reason.messageEn) : t("common.error")))
    }, 700)
    return () => window.clearInterval(timer)
  }, [job, zh, t])

  const active = history.find((item) => item.id === activeId) || null
  const compared = history.find((item) => item.id === compareId) || null
  const study = active?.study
  const points = study?.points || study?.pareto || []
  const units = useMemo(() => unitMap(study), [study])
  const chosen = points.find((point) => point.id === selected) || null
  const other = points.find((point) => point.id === pinned) || null

  async function start(kind: string, options: Record<string, unknown>) {
    setError("")
    setJob(null)
    try {
      const started = await api.startAnalysis({
        kind,
        dsl,
        project_id: projectId ? Number(projectId) : undefined,
        options: { solver, ...options },
      })
      setJob(started)
      if (started.status !== "running" && started.status !== "queued") adopt(started)
    } catch (reason) {
      setError(reason instanceof ApiError ? (zh ? reason.message : reason.messageEn) : t("common.error"))
    }
  }

  function adopt(next: AnalysisJob) {
    if (next.result) {
      const saved = { id: next.id, kind: next.result.kind || next.kind, at: new Date().toISOString(), study: next.result }
      setHistory((current) => [saved, ...current.filter((item) => item.id !== saved.id)])
      setActiveId(saved.id)
      setSelected(null)
      setCoupling(null)
      return
    }
    if (next.error || next.error_en) setError(zh ? next.error : next.error_en)
  }

  function runWizard() {
    const count = Number(samples) || 16
    if (wizard === "doe") void start("doe", { method, samples: count, surrogate, seed: 1 })
    else if (wizard === "sensitivity") void start(mode === "morris" || mode === "sobol" ? mode : "local", { samples: count, trajectories: 6, seed: 1 })
    else if (wizard === "uq") void start(mode === "form" ? "form" : "uq", { method: mode === "lhs" ? "lhs" : "monte-carlo", samples: count, cv: 0.08, seed: 1, form: mode === "form" })
    else if (wizard === "mdo") void start("mdo", { template, architecture, mda })
    else if (wizard === "multi") void start("multi", { method: multi, generations: 20, population: 28, seed: 1 })
    else void start(mode || "sweep", { samples: count, steps: 7, mode: "two-stage", alpha: 0.05, cv: 0.08 })
  }

  const running = job?.status === "running" || job?.status === "queued"
  let figure = 1
  const next = () => figure++

  return (
    <div className="flex h-full min-h-[420px] flex-col" data-analysis-board>
      <div className="flex flex-wrap items-end gap-2 border-b px-3 py-2">
        <div className="min-w-0 flex-1">
          <div className="text-sm font-medium">{t("analysis.workbench")}</div>
          <p className="text-xs text-muted-foreground">{t("analysis.lead")}</p>
        </div>
        <div className="flex flex-wrap gap-1">
          {WIZARDS.map((item) => (
            <Button key={item} size="xs" variant={wizard === item ? "default" : "outline"} aria-pressed={wizard === item} onClick={() => setWizard(item)}>
              {t(`analysis.${item}`)}
            </Button>
          ))}
        </div>
      </div>
      <div className="flex flex-wrap items-end gap-2 border-b px-3 py-2">
        {wizard === "doe" ? (
          <>
            <Field label={t("analysis.method")}>
              <Choice value={method} onChange={setMethod} options={["full-factorial", "fractional", "lhs", "sobol", "halton", "ccd", "box-behnken"]} />
            </Field>
            <Field label={t("analysis.surrogate")}>
              <Choice value={surrogate} onChange={setSurrogate} options={["polynomial", "kriging", "rbf"]} />
            </Field>
          </>
        ) : null}
        {wizard === "sensitivity" ? (
          <Field label={t("analysis.method")}>
            <Choice value={mode} onChange={setMode} options={["local", "morris", "sobol"]} labels={{ local: t("analysis.local"), morris: "Morris", sobol: "Sobol" }} />
          </Field>
        ) : null}
        {wizard === "uq" ? (
          <Field label={t("analysis.method")}>
            <Choice value={mode} onChange={setMode} options={["monte-carlo", "lhs", "form"]} labels={{ form: "FORM" }} />
          </Field>
        ) : null}
        {wizard === "mdo" ? (
          <>
            <Field label={t("analysis.template")}>
              <Choice value={template} onChange={setTemplate} options={["sellar", "wing", "supply"]} labels={{ sellar: "Sellar", wing: zh ? "机翼" : "Wing", supply: zh ? "供应链" : "Supply chain" }} />
            </Field>
            <Field label={t("analysis.architecture")}>
              <Choice value={architecture} onChange={setArchitecture} options={["mdf", "idf", "co", "bliss", "openmdao"]} />
            </Field>
            <Field label={t("analysis.mda")}>
              <Choice value={mda} onChange={setMda} options={["gauss-seidel", "newton"]} />
            </Field>
          </>
        ) : null}
        {wizard === "multi" ? (
          <Field label={t("analysis.method")}>
            <Choice value={multi} onChange={setMulti} options={["weighted", "epsilon", "nsga2", "nsga3"]} />
          </Field>
        ) : null}
        {wizard === "more" ? (
          <Field label={t("analysis.method")}>
            <Choice value={mode} onChange={setMode} options={["sweep", "robust", "chance", "iis", "quality", "schedule"]} labels={{ sweep: t("analysis.sweep"), robust: t("analysis.robust"), chance: t("analysis.chance"), iis: t("analysis.iis"), quality: t("analysis.quality"), schedule: t("analysis.schedule") }} />
          </Field>
        ) : null}
        {wizard !== "mdo" && wizard !== "more" ? (
          <Field label={t("analysis.samples")}>
            <Input className="h-8 w-20" value={samples} onChange={(event) => setSamples(event.target.value)} inputMode="numeric" />
          </Field>
        ) : null}
        <Button size="sm" onClick={runWizard} disabled={running}>{t("analysis.run")}</Button>
        <Button size="sm" variant="outline" disabled={!running || !job} onClick={() => job && void api.cancelAnalysis(job.id).then(setJob)}>{t("analysis.cancel")}</Button>
        <Button size="xs" variant="ghost" onClick={() => setZoom((value) => Math.min(1.8, Number((value + 0.15).toFixed(2))))}>{t("analysis.zoomIn")}</Button>
        <Button size="xs" variant="ghost" onClick={() => setZoom((value) => Math.max(0.7, Number((value - 0.15).toFixed(2))))}>{t("analysis.zoomOut")}</Button>
      </div>
      {running && job ? (
        <div className="border-b px-3 py-1.5 text-xs" data-analysis-progress={Math.round((job.progress || 0) * 100)}>
          <div className="mb-1 flex justify-between">
            <span>{zh ? job.message : job.message_en}</span>
            <span>{Math.round((job.progress || 0) * 100)}%</span>
          </div>
          <div className="h-1 bg-muted"><div className="h-full bg-primary" style={{ width: `${Math.round((job.progress || 0) * 100)}%` }} /></div>
        </div>
      ) : null}
      {error ? <p className="border-b px-3 py-2 text-xs text-destructive">{error}</p> : null}
      {proposals?.length ? (
        <div className="flex flex-wrap items-center gap-1 border-b px-3 py-1.5 text-xs">
          <span className="text-muted-foreground">{t("analysis.proposals")}</span>
          {proposals.map((item) => (
            <Button key={`${item.kind}-${item.reason_en}`} size="xs" variant="outline" onClick={() => void start(item.kind, item.options || {})}>
              {zh ? item.reason_zh : item.reason_en}
            </Button>
          ))}
        </div>
      ) : null}
      <div className="grid min-h-0 flex-1 lg:grid-cols-[180px_minmax(0,1fr)_220px]">
        <aside className="border-b lg:border-r lg:border-b-0">
          <div className="px-2 py-1 text-[11px] font-medium tracking-wide text-muted-foreground uppercase">{t("analysis.history")}</div>
          {history.length === 0 ? <p className="px-2 py-2 text-xs text-muted-foreground">{t("analysis.empty")}</p> : null}
          <ul className="max-h-48 overflow-auto lg:max-h-none">
            {history.map((item) => (
              <li key={item.id}>
                <button type="button" className={`block w-full px-2 py-1 text-left text-xs hover:bg-muted ${item.id === activeId ? "bg-muted" : ""}`} onClick={() => { setActiveId(item.id); setSelected(null); setCoupling(null) }}>
                  <div className="font-medium">{labelOf(item.kind, zh)}</div>
                  <div className="truncate text-muted-foreground">{metricLine(item.study)}</div>
                </button>
                <button type="button" className="px-2 pb-1 text-[11px] text-muted-foreground" onClick={() => setCompareId(item.id === compareId ? null : item.id)}>
                  {item.id === compareId ? t("analysis.clearPin") : t("analysis.compare")}
                </button>
              </li>
            ))}
          </ul>
        </aside>
        <div className="min-h-0 overflow-auto" style={{ zoom }}>
          {!study ? <p className="px-3 py-6 text-sm text-muted-foreground">{t("analysis.empty")}</p> : (
            <div className="min-w-[720px] space-y-3 p-3">
              <p className="text-xs text-muted-foreground">{t("analysis.linked")}</p>
              {study.ok === false ? <p className="text-sm">{zh ? study.message : study.message_en}</p> : null}
              {study.note ? <p className="text-xs">{zh ? study.note : study.note_en || study.note}</p> : null}
              <Summary study={study} zh={zh} />
              {compared ? (
                <div className="grid gap-2 sm:grid-cols-2" data-analysis-compare>
                  <Summary study={study} zh={zh} title={labelOf(study.kind || "", zh)} />
                  <Summary study={compared.study} zh={zh} title={labelOf(compared.kind, zh)} />
                </div>
              ) : null}
              {study.n2 ? <N2Chart diagram={study.n2} index={next()} zh={zh} onInspect={setCoupling} /> : null}
              {coupling ? (
                <p className="text-xs" data-n2-inspect>
                  {t("analysis.n2cell")}: {coupling.from} → {coupling.to}. {coupling.variables.join(", ") || (zh ? "对角学科" : "Diagonal discipline")}
                </p>
              ) : null}
              {study.disciplines?.length ? (
                <section>
                  <h3 className="mb-1 text-sm font-medium">{t("analysis.disciplines")}</h3>
                  <ul className="space-y-1 text-xs">
                    {study.disciplines.map((row) => (
                      <li key={row.name} className="border px-2 py-1">
                        <span className="font-medium">{row.name}</span>
                        <span className="text-muted-foreground"> {Object.entries(row.outputs).map(([key, value]) => `${key}=${Number(value).toPrecision(4)}`).join(", ")}</span>
                      </li>
                    ))}
                  </ul>
                </section>
              ) : null}
              {paretoPoints(points).length ? <ParetoChart points={paretoPoints(points)} index={next()} zh={zh} selected={selected} compare={pinned} onSelect={setSelected} units={units} /> : null}
              {points.length >= 4 ? <ParallelChart points={points} index={next()} zh={zh} selected={selected} compare={pinned} onSelect={setSelected} units={units} /> : null}
              {points.length >= 4 ? <MatrixChart points={points} index={next()} zh={zh} selected={selected} compare={pinned} onSelect={setSelected} units={units} /> : null}
              {study.surface ? <SurfaceChart surface={study.surface} index={next()} zh={zh} /> : null}
              {sobolRows(study).length ? <SobolChart rows={sobolRows(study)} index={next()} zh={zh} /> : null}
              {morrisRows(study).length ? <MorrisChart rows={morrisRows(study)} index={next()} zh={zh} /> : null}
              {study.tornado?.length ? <TornadoChart rows={study.tornado} index={next()} zh={zh} /> : null}
              {study.effects ? <EffectsChart effects={study.effects} index={next()} zh={zh} /> : null}
              {(study.convergence || study.history || []).length ? <HistoryChart rows={study.convergence || study.history || []} index={next()} zh={zh} /> : null}
              {study.values?.length ? <DistributionChart values={study.values} histogram={study.histogram} index={next()} zh={zh} /> : null}
              {study.correlation?.labels?.length ? <Heatmap correlation={study.correlation} index={next()} zh={zh} /> : null}
              {study.gantt?.length ? <ScheduleChart rows={study.gantt} index={next()} zh={zh} selected={selected} onSelect={setSelected} /> : null}
              {study.duals ? <NumberTable title={zh ? "对偶与既约费用" : "Duals and reduced costs"} rows={dualRows(study)} /> : null}
              {study.iis ? <p className="text-sm">{zh ? study.iis.message : study.iis.message_en}</p> : null}
              {study.quality ? <NumberTable title={zh ? "解的质量" : "Solution quality"} rows={Object.entries(study.quality).map(([name, value]) => ({ name, value }))} /> : null}
            </div>
          )}
        </div>
        <aside className="border-t lg:border-t-0 lg:border-l" data-design-details>
          <div className="flex items-center justify-between px-2 py-1">
            <span className="text-[11px] font-medium tracking-wide text-muted-foreground uppercase">{t("analysis.details")}</span>
            <Button size="xs" variant="ghost" disabled={!selected} onClick={() => setPinned(selected)}>{t("analysis.pin")}</Button>
          </div>
          {!chosen ? <p className="px-2 py-2 text-xs text-muted-foreground">{t("analysis.noPoint")}</p> : <PointCard point={chosen} other={other} units={units} zh={zh} />}
        </aside>
      </div>
    </div>
  )
}

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <Label className="grid gap-1 text-[11px] text-muted-foreground">
      {label}
      {children}
    </Label>
  )
}

function Choice({ value, onChange, options, labels }: { value: string; onChange: (value: string) => void; options: string[]; labels?: Record<string, string> }) {
  return (
    <Select value={value} onValueChange={onChange}>
      <SelectTrigger className="h-8 w-40 text-xs"><SelectValue /></SelectTrigger>
      <SelectContent>
        {options.map((item) => <SelectItem key={item} value={item}>{labels?.[item] || item}</SelectItem>)}
      </SelectContent>
    </Select>
  )
}

function Summary({ study, zh, title }: { study: Study; zh: boolean; title?: string }) {
  const metrics = study.summary_metrics || {}
  const rows = Object.entries(metrics).filter(([, value]) => value !== null && value !== undefined && typeof value !== "object")
  return (
    <div className="border px-2 py-1 text-xs">
      {title ? <div className="font-medium">{title}</div> : null}
      <div className="flex flex-wrap gap-x-3 gap-y-1">
        {study.objective !== undefined && study.objective !== null ? <span>{zh ? "目标" : "Objective"} {Number(study.objective).toPrecision(6)}</span> : null}
        {study.violation !== undefined ? <span>{zh ? "违反" : "Violation"} {Number(study.violation).toPrecision(3)}</span> : null}
        {study.beta !== undefined ? <span>β {Number(study.beta).toPrecision(4)}</span> : null}
        {study.surrogate?.cv?.r2 !== undefined && study.surrogate.cv.r2 !== null ? <span>R² {Number(study.surrogate.cv.r2).toFixed(3)}</span> : null}
        {rows.map(([key, value]) => <span key={key}>{key} {typeof value === "number" ? Number(value).toPrecision(4) : String(value)}</span>)}
      </div>
      {study.surrogate?.error ? <p className="text-destructive">{zh ? study.surrogate.error : study.surrogate.error_en}</p> : null}
    </div>
  )
}

function PointCard({ point, other, units, zh }: { point: StudyPoint; other: StudyPoint | null; units: Record<string, string>; zh: boolean }) {
  const keys = Array.from(new Set([...Object.keys(point.values || {}), ...Object.keys(point.objectives || {})]))
  return (
    <table className="w-full text-xs">
      <thead>
        <tr className="text-left text-muted-foreground">
          <th className="px-2 py-1">{zh ? "量" : "Quantity"}</th>
          <th className="px-2 py-1">{point.label || point.id}</th>
          {other ? <th className="px-2 py-1">{other.label || other.id}</th> : null}
        </tr>
      </thead>
      <tbody>
        {keys.map((key) => (
          <tr key={key} className="border-t">
            <td className="px-2 py-1">{key}{units[key] ? ` (${units[key]})` : ""}</td>
            <td className="px-2 py-1">{formatPoint(point, key)}</td>
            {other ? <td className="px-2 py-1">{formatPoint(other, key)}</td> : null}
          </tr>
        ))}
      </tbody>
    </table>
  )
}

function NumberTable({ title, rows }: { title: string; rows: Array<{ name: string; value: number }> }) {
  return (
    <section>
      <h3 className="mb-1 text-sm font-medium">{title}</h3>
      <table className="w-full text-xs">
        <tbody>
          {rows.map((row) => (
            <tr key={row.name} className="border-t">
              <td className="px-2 py-1">{row.name}</td>
              <td className="px-2 py-1 text-right">{Number(row.value).toPrecision(4)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  )
}

function focusToWizard(focus?: string): (typeof WIZARDS)[number] | null {
  if (!focus) return null
  if (focus === "doe") return "doe"
  if (focus === "local" || focus === "morris" || focus === "sobol" || focus === "sensitivity") return "sensitivity"
  if (focus === "uq" || focus === "form") return "uq"
  if (focus === "mdo") return "mdo"
  if (focus === "multi") return "multi"
  if (["sweep", "robust", "chance", "iis", "quality", "schedule"].includes(focus)) return "more"
  return null
}

function unitMap(study?: Study) {
  const units = { ...(study?.units || {}) }
  for (const column of study?.columns || []) if (column.unit) units[column.key] = column.unit
  return units
}

function paretoPoints(points: StudyPoint[]) {
  return points.filter((point) => point.minimize && point.minimize.length >= 2)
}

function sobolRows(study: Study) {
  return (study.rows || []).filter((row) => typeof row.S1 === "number" && typeof row.ST === "number") as Array<{ name: string; S1: number; ST: number }>
}

function morrisRows(study: Study) {
  return (study.rows || []).filter((row) => typeof row.mu_star === "number") as Array<{ name: string; mu_star: number; sigma: number }>
}

function dualRows(study: Study) {
  const rows = Object.entries(study.duals || {}).map(([name, value]) => ({ name: `λ ${name}`, value }))
  for (const [name, value] of Object.entries(study.reduced_costs || {})) rows.push({ name: `rc ${name}`, value })
  return rows
}

function formatPoint(point: StudyPoint, key: string) {
  const value = point.values?.[key] ?? point.objectives?.[key]
  return typeof value === "number" ? value.toPrecision(4) : "—"
}

function metricLine(study: Study) {
  if (study.objective !== undefined && study.objective !== null) return Number(study.objective).toPrecision(4)
  const r2 = study.surrogate?.cv?.r2
  if (typeof r2 === "number") return `R² ${r2.toFixed(3)}`
  if (study.message) return study.message
  return study.kind || ""
}

function labelOf(kind: string, zh: boolean) {
  const names: Record<string, [string, string]> = {
    doe: ["试验设计", "DOE"],
    local: ["局部灵敏度", "Local sensitivity"],
    morris: ["Morris", "Morris"],
    sobol: ["Sobol", "Sobol"],
    mdo: ["多学科", "MDO"],
    multi: ["多目标", "Multi-objective"],
    uq: ["不确定性", "Uncertainty"],
    sweep: ["扫描", "Sweep"],
    schedule: ["调度", "Schedule"],
    iis: ["不可行", "Infeasibility"],
    robust: ["稳健", "Robust"],
    chance: ["机会约束", "Chance"],
    form: ["FORM", "FORM"],
  }
  const pair = names[kind]
  return pair ? (zh ? pair[0] : pair[1]) : kind
}
