import { useEffect, useState } from "react"
import { Link, useParams } from "react-router-dom"
import { useTranslation } from "react-i18next"
import { toast } from "sonner"
import { AmlEditor } from "@/components/aml-editor"
import { ResultsPanel } from "@/components/results-panel"
import { Timeline } from "@/components/timeline"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Switch } from "@/components/ui/switch"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { Textarea } from "@/components/ui/textarea"
import { ApiError, api } from "@/lib/api"
import type { Project, Run, RunEvent, SolverInfo } from "@/lib/types"

const live = new Set(["queued", "running", "awaiting_approval"])

export function ProjectPage() {
  const { id = "" } = useParams()
  const { t, i18n } = useTranslation()
  const [project, setProject] = useState<Project | null>(null)
  const [title, setTitle] = useState("")
  const [statement, setStatement] = useState("")
  const [dsl, setDsl] = useState("")
  const [solver, setSolver] = useState("highs")
  const [solvers, setSolvers] = useState<SolverInfo[]>([])
  const [auto, setAuto] = useState(false)
  const [run, setRun] = useState<Run | null>(null)
  const [events, setEvents] = useState<RunEvent[]>([])
  const [tab, setTab] = useState("problem")
  const [error, setError] = useState("")
  const [exportCode, setExportCode] = useState("")
  const [target, setTarget] = useState("pyomo")

  useEffect(() => {
    let stop = false
    api.project(Number(id)).then((item) => {
      if (stop) return
      setProject(item)
      setTitle(item.title)
      setStatement(item.statement)
      setDsl(item.dsl)
    }).catch((reason: unknown) => setError(reason instanceof ApiError ? reason.message : t("common.error")))
    api.runs(Number(id)).then((rows) => {
      if (!stop && rows[0]) setRun(rows[0])
    }).catch(() => undefined)
    api.solvers().then(setSolvers).catch(() => undefined)
    return () => {
      stop = true
    }
  }, [id, t])

  const runId = run?.id
  const runStatus = run?.status
  useEffect(() => {
    if (!runId) return
    api.events(runId).then(setEvents).catch(() => undefined)
    if (!runStatus || !live.has(runStatus)) return
    const timer = window.setInterval(() => {
      api.run(runId).then(setRun).catch(() => undefined)
      api.events(runId).then(setEvents).catch(() => undefined)
    }, 1000)
    return () => window.clearInterval(timer)
  }, [runId, runStatus])

  async function save() {
    const next = await api.updateProject(Number(id), { title, statement, dsl })
    setProject(next)
    toast.success(t("studio.saved"))
  }

  async function solve() {
    try {
      await save()
      const started = await api.startRun(Number(id), {
        statement,
        dsl,
        solver,
        auto_approve: auto,
        locale: i18n.language.startsWith("zh") ? "zh-CN" : "en",
      })
      setRun(started)
      setEvents([])
      setTab("agents")
      toast.success(t("studio.started"))
    } catch (reason) {
      toast.error(reason instanceof ApiError ? (i18n.language.startsWith("zh") ? reason.message : reason.messageEn) : t("common.error"))
    }
  }

  async function decide(decision: "approved" | "rejected") {
    if (!run) return
    const next = await api.decide(run.id, decision)
    setRun(next)
  }

  async function validateModel() {
    const result = await api.validate(dsl)
    if (result.ok) {
      if (result.aml) setDsl(result.aml)
      toast.success(t("studio.valid"))
    } else {
      const first = result.diagnostics[0]
      toast.error(i18n.language.startsWith("zh") ? first?.message : first?.message_en)
    }
  }

  async function doImport(file: File) {
    const text = await file.text()
    const format = file.name.toLowerCase().endsWith(".mps") ? "mps" : "lp"
    const imported = await api.importModel(format, text)
    setDsl(imported.aml)
    setTab("model")
    toast.success(imported.ok ? t("studio.valid") : t("studio.invalid"))
  }

  async function exportModel() {
    const source = dsl || run?.dsl || ""
    const translated = await api.translate(source, target)
    setExportCode(translated.code)
  }

  if (error) return <p className="text-sm text-destructive">{error}</p>
  if (!project) return <p className="text-sm text-muted-foreground">{t("common.loading")}</p>

  const zh = i18n.language.startsWith("zh")
  const questions = run?.result?.questions || run?.result?.formulation?.questions || []

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3">
        <Input className="max-w-md text-lg font-medium" value={title} onChange={(event) => setTitle(event.target.value)} />
        <Badge variant="secondary">{t(`status.${project.status}`, { defaultValue: project.status })}</Badge>
        {run ? <Link className="text-xs text-muted-foreground hover:underline" to={`/runs/${run.id}`}>#{run.id}</Link> : null}
        <div className="ml-auto flex flex-wrap items-center gap-2">
          <Label className="flex items-center gap-2 text-xs">
            <Switch checked={auto} onCheckedChange={setAuto} />
            {t("studio.auto")}
          </Label>
          <Select value={solver} onValueChange={setSolver}>
            <SelectTrigger className="w-36"><SelectValue placeholder={t("studio.solver")} /></SelectTrigger>
            <SelectContent>
              {solvers.filter((item) => item.available).map((item) => (
                <SelectItem key={item.name} value={item.name}>{item.label}</SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Button variant="outline" onClick={() => void save()}>{t("studio.save")}</Button>
          <Button onClick={() => void solve()}>{t("studio.solve")}</Button>
        </div>
      </div>

      {run?.pending_gate ? (
        <Card className="border-primary/40">
          <CardContent className="flex flex-wrap items-center gap-3 py-4">
            <div>
              <div className="text-sm font-medium">{t("studio.waiting")}</div>
              <div className="text-xs text-muted-foreground">{run.pending_gate.gate}</div>
            </div>
            <div className="ml-auto flex gap-2">
              <Button variant="outline" onClick={() => void decide("rejected")}>{t("studio.reject")}</Button>
              <Button onClick={() => void decide("approved")}>{t("studio.approve")}</Button>
            </div>
          </CardContent>
        </Card>
      ) : null}

      {run?.status === "failed" && run.error ? <p className="text-sm text-destructive">{zh ? run.error : run.error_en || run.error}</p> : null}

      <Tabs value={tab} onValueChange={setTab}>
        <TabsList>
          <TabsTrigger value="problem">{t("studio.problem")}</TabsTrigger>
          <TabsTrigger value="model">{t("studio.model")}</TabsTrigger>
          <TabsTrigger value="agents">{t("studio.agents")}</TabsTrigger>
          <TabsTrigger value="results">{t("studio.results")}</TabsTrigger>
          <TabsTrigger value="export">{t("studio.export")}</TabsTrigger>
        </TabsList>
        <TabsContent value="problem" className="space-y-3">
          <Textarea value={statement} onChange={(event) => setStatement(event.target.value)} rows={12} placeholder={t("projects.statement")} />
          {questions.length ? (
            <Card>
              <CardContent className="space-y-1 py-4 text-sm">
                <div className="font-medium">{t("studio.questions")}</div>
                {questions.map((item) => <div key={item}>{item}</div>)}
              </CardContent>
            </Card>
          ) : null}
        </TabsContent>
        <TabsContent value="model" className="space-y-3">
          <div className="flex flex-wrap gap-2">
            <Button variant="outline" onClick={() => void validateModel()}>{t("studio.validate")}</Button>
            <Label className="inline-flex cursor-pointer items-center rounded-lg border px-3 py-1.5 text-sm">
              {t("studio.import")}
              <input
                className="hidden"
                type="file"
                accept=".lp,.mps,.txt"
                onChange={(event) => {
                  const file = event.target.files?.[0]
                  if (file) void doImport(file)
                }}
              />
            </Label>
          </div>
          <AmlEditor value={dsl} onChange={setDsl} />
        </TabsContent>
        <TabsContent value="agents">
          {events.length === 0 ? <p className="text-sm text-muted-foreground">{t("studio.emptyRun")}</p> : <Timeline events={events} />}
        </TabsContent>
        <TabsContent value="results">
          {run ? <ResultsPanel run={run} /> : <p className="text-sm text-muted-foreground">{t("results.empty")}</p>}
        </TabsContent>
        <TabsContent value="export" className="space-y-3">
          <div className="flex gap-2">
            <Select value={target} onValueChange={setTarget}>
              <SelectTrigger className="w-40"><SelectValue /></SelectTrigger>
              <SelectContent>
                {["pyomo", "pulp", "ortools", "cvxpy", "ampl", "gams", "jump", "lp", "mps"].map((item) => (
                  <SelectItem key={item} value={item}>{item}</SelectItem>
                ))}
              </SelectContent>
            </Select>
            <Button variant="outline" onClick={() => void exportModel()}>{t("studio.export")}</Button>
          </div>
          <pre className="max-h-[480px] overflow-auto rounded-xl border bg-card p-4 text-xs">{exportCode || run?.result?.translations?.[target]?.code || ""}</pre>
        </TabsContent>
      </Tabs>
    </div>
  )
}
