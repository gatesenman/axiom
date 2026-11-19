import { lazy, Suspense, useEffect, useRef, useState, type ComponentProps, type FormEvent, type MouseEvent as ReactMouseEvent, type ReactNode } from "react"
import { useLocation, useMatch, useNavigate } from "react-router-dom"
import { useTranslation } from "react-i18next"
import { useTheme } from "next-themes"
import { toast } from "sonner"
import { redo, undo } from "@codemirror/commands"
import type { ReactCodeMirrorRef } from "@uiw/react-codemirror"
import {
  Bot,
  Check,
  ChevronDown,
  ChevronRight,
  Download,
  FilePlus,
  FolderOpen,
  Library,
  MessageSquare,
  PanelBottom,
  LineChart,
  Play,
  Save,
  Settings,
  Square,
  X,
} from "lucide-react"
import { AmlEditor, revealLine } from "@/components/aml-editor"
import { ImportWizard } from "@/components/import-wizard"
import { IndustryGallery } from "@/components/industry-gallery"
import { openSearchPanel } from "@codemirror/search"
import { VersionHistory, type VersionRow } from "@/components/version-history"
import { Timeline } from "@/components/timeline"
import { SidecarBanner } from "@/components/sidecar-banner"
import { SignInForm } from "@/pages/login"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { CommandDialog, CommandEmpty, CommandGroup, CommandInput, CommandItem, CommandList, CommandShortcut } from "@/components/ui/command"
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuShortcut,
  DropdownMenuSub,
  DropdownMenuSubContent,
  DropdownMenuSubTrigger,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Switch } from "@/components/ui/switch"
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { Textarea } from "@/components/ui/textarea"
import { ApiError, api, downloadPackage, downloadReport } from "@/lib/api"
import { useAuth } from "@/lib/auth"
import type { AmlDiagnostic } from "@/lib/diagnostics"
import { diagnosticLabel } from "@/lib/diagnostics"
import { copyText, executiveSummary, progressPercent } from "@/lib/decision"
import { historyPush, historyRedo, historyStart, historyUndo, type HistoryState } from "@/lib/history"
import { notifyFinished } from "@/lib/notify"
import { clearDraft, draftDiffers, loadDraft, saveDraft, type Draft } from "@/lib/recovery"
import { clampSize, loadLayout, saveLayout } from "@/lib/layout"
import type { AnalysisProposal, Study } from "@/components/analysis/types"
import type { Project, Run, RunEvent, Settings as LlmSettings, SolverInfo, StandardForm, TemplateInfo } from "@/lib/types"

const ParameterGrid = lazy(() => import("@/components/parameter-grid").then((mod) => ({ default: mod.ParameterGrid })))
const ResultsPanel = lazy(() => import("@/components/results-panel").then((mod) => ({ default: mod.ResultsPanel })))
const StandardEquations = lazy(() => import("@/components/standard-equations").then((mod) => ({ default: mod.StandardEquations })))
const WhatIfPanel = lazy(() => import("@/components/what-if-panel").then((mod) => ({ default: mod.WhatIfPanel })))
const AnalysisBoard = lazy(() => import("@/components/analysis/board").then((mod) => ({ default: mod.AnalysisBoard })))
const LifecycleBoard = lazy(() => import("@/components/lifecycle/board").then((mod) => ({ default: mod.LifecycleBoard })))
const CompatibilityDialog = lazy(() => import("@/components/analysis/compatibility").then((mod) => ({ default: mod.CompatibilityDialog })))
const AuditPage = lazy(() => import("@/pages/audit").then((mod) => ({ default: mod.AuditPage })))
const SettingsPage = lazy(() => import("@/pages/settings").then((mod) => ({ default: mod.SettingsPage })))
const WorkspacesPage = lazy(() => import("@/pages/workspaces").then((mod) => ({ default: mod.WorkspacesPage })))

type DocId = "problem" | "model" | "data" | "equations" | "results" | "analysis" | "export" | "lifecycle"
type BottomTab = "agents" | "solver" | "diagnostics" | "console"
type Side = "explorer" | "templates"

const live = new Set(["queued", "running", "awaiting_approval"])

function formatOf(name: string): string | null {
  const lower = name.toLowerCase()
  const pairs: [string, string][] = [
    [".dat-s", "sdpa"],
    [".axiom", "aml"],
    [".aml", "aml"],
    [".qps", "qps"],
    [".osil", "osil"],
    [".xml", "osil"],
    [".cbf", "cbf"],
    [".sdpa", "sdpa"],
    [".fzn", "flatzinc"],
    [".mzn", "minizinc"],
    [".mps", "mps"],
    [".gms", "gams"],
    [".zpl", "zimpl"],
    [".mod", "mod"],
    [".opl", "opl"],
    [".txt", "lp"],
    [".lp", "lp"],
    [".nl", "nl"],
    [".py", "py"],
    [".jl", "jump"],
  ]
  for (const [ext, fmt] of pairs) {
    if (lower.endsWith(ext)) return fmt
  }
  return null
}

export function Workbench() {
  const { t, i18n } = useTranslation()
  const { user, ready, logout, refresh } = useAuth()
  const { setTheme, resolvedTheme } = useTheme()
  const navigate = useNavigate()
  const location = useLocation()
  const projectMatch = useMatch("/projects/:id")
  const runMatch = useMatch("/runs/:id")
  const routeDialog = location.pathname === "/settings" ? "settings" : location.pathname === "/workspaces" ? "workspaces" : location.pathname === "/audit" ? "audit" : location.pathname === "/templates" ? "templates" : null
  const rememberedProject = useRef<string | undefined>(undefined)
  if (projectMatch?.params.id) rememberedProject.current = projectMatch.params.id
  const projectId = projectMatch?.params.id || (routeDialog ? rememberedProject.current : undefined)
  const zh = i18n.language.startsWith("zh")

  const storedLayout = useRef(loadLayout())
  const actions = useRef({ save: () => {}, solve: () => {}, validate: () => {}, undo: () => {}, redo: () => {}, copyConclusion: () => {} })
  const historyRef = useRef<HistoryState>(historyStart(""))
  const restoring = useRef(false)
  const snapTimer = useRef(0)
  const seenRun = useRef<string | null>(null)
  const [projects, setProjects] = useState<Project[] | null>(null)
  const [templates, setTemplates] = useState<TemplateInfo[]>([])
  const [solvers, setSolvers] = useState<SolverInfo[]>([])
  const [llm, setLlm] = useState<LlmSettings | null>(null)
  const [title, setTitle] = useState("")
  const [statement, setStatement] = useState("")
  const [dsl, setDsl] = useState("")
  const [solver, setSolver] = useState("highs")
  const [algorithms, setAlgorithms] = useState<{ id: string; solver: string; label_zh: string; label_en: string }[]>([
    { id: "auto", solver: "highs", label_zh: "自动", label_en: "Auto" },
  ])
  const [algorithm, setAlgorithm] = useState("auto")
  const [dropping, setDropping] = useState(false)
  const [auto, setAuto] = useState(false)
  const [run, setRun] = useState<Run | null>(null)
  const [runs, setRuns] = useState<Run[]>([])
  const [events, setEvents] = useState<RunEvent[]>([])
  const [celebrate, setCelebrate] = useState(false)
  const [shortcutsOpen, setShortcutsOpen] = useState(false)
  const [tourOn, setTourOn] = useState(() => localStorage.getItem("axiom.tour") !== "done")
  const [tourStep, setTourStep] = useState(0)
  const [doc, setDoc] = useState<DocId>(() => {
    const value = storedLayout.current.doc
    return value === "problem" || value === "model" || value === "data" || value === "equations" || value === "results" || value === "analysis" || value === "export" ? value : "problem"
  })
  const [equations, setEquations] = useState<StandardForm | null>(null)
  const [equationState, setEquationState] = useState<"empty" | "loading" | "ready" | "error">("empty")
  const [bottomTab, setBottomTab] = useState<BottomTab>("agents")
  const [side, setSide] = useState<Side>("explorer")
  const [leftOpen, setLeftOpen] = useState(() => window.innerWidth >= 768 && storedLayout.current.leftOpen !== false)
  const [rightOpen, setRightOpen] = useState(() => window.innerWidth >= 1100 && storedLayout.current.rightOpen !== false)
  const [rightTab, setRightTab] = useState<"inspector" | "chat">("inspector")
  const [bottomOpen, setBottomOpen] = useState(() => storedLayout.current.bottomOpen !== false)
  const [leftWidth, setLeftWidth] = useState(() => clampSize(storedLayout.current.leftWidth, 248, 180, 460))
  const [rightWidth, setRightWidth] = useState(() => clampSize(storedLayout.current.rightWidth, 280, 220, 460))
  const [bottomHeight, setBottomHeight] = useState(() => clampSize(storedLayout.current.bottomHeight, 168, 96, 420))
  const [minimap, setMinimap] = useState(() => storedLayout.current.minimap === true)
  const [diagnostics, setDiagnostics] = useState<AmlDiagnostic[]>([])
  const [savedMark, setSavedMark] = useState("")
  const [exporting, setExporting] = useState(false)
  const [gotoOpen, setGotoOpen] = useState(false)
  const [gotoLine, setGotoLine] = useState("1")
  const [narrow, setNarrow] = useState(() => window.innerWidth < 768)
  const [paletteOpen, setPaletteOpen] = useState(false)
  const [newOpen, setNewOpen] = useState(false)
  const [aboutOpen, setAboutOpen] = useState(false)
  const [compatOpen, setCompatOpen] = useState(false)
  const [analysisFocus, setAnalysisFocus] = useState("mdo")
  const [analysisSeed, setAnalysisSeed] = useState<{ token: number; study: Study } | null>(null)
  const [analysisProposals, setAnalysisProposals] = useState<AnalysisProposal[]>([])
  const [newTitle, setNewTitle] = useState("")
  const [newStatement, setNewStatement] = useState("")
  const [target, setTarget] = useState("pyomo")
  const [targets, setTargets] = useState(["pyomo", "pulp", "ortools", "cvxpy", "ampl", "gams", "jump", "lp", "mps"])
  const [exportCode, setExportCode] = useState("")
  const [cursor, setCursor] = useState({ line: 1, column: 1 })
  const [consoleLines, setConsoleLines] = useState<string[]>([])
  const [chat, setChat] = useState<{ role: string; content: string }[]>([])
  const [chatDraft, setChatDraft] = useState("")
  const [chatPending, setChatPending] = useState(false)
  const [expanded, setExpanded] = useState<number | null>(null)
  const [menu, setMenu] = useState<{ x: number; y: number; id: number } | null>(null)
  const [loadError, setLoadError] = useState("")
  const [advice, setAdvice] = useState<{ solver: string; reason_zh: string; reason_en: string; algorithm?: string } | null>(null)
  const [versions, setVersions] = useState<VersionRow[]>([])
  const [galleryOpen, setGalleryOpen] = useState(false)
  const [wizardFile, setWizardFile] = useState<File | null>(null)
  const [restore, setRestore] = useState<Draft | null>(null)
  const [equationFocus, setEquationFocus] = useState<string | null>(null)
  const [notifyOn, setNotifyOn] = useState(() => localStorage.getItem("axiom.notify") !== "0")
  const [soundOn, setSoundOn] = useState(() => localStorage.getItem("axiom.sound") === "1")
  const editorRef = useRef<ReactCodeMirrorRef>(null)
  const importRef = useRef<HTMLInputElement>(null)
  const mathRef = useRef<HTMLInputElement>(null)
  const dataRef = useRef<HTMLInputElement>(null)
  const leftPanelRef = useRef<HTMLElement>(null)
  const rightPanelRef = useRef<HTMLElement>(null)
  const bottomPanelRef = useRef<HTMLElement>(null)
  const celebrated = useRef(false)

  function log(line: string) {
    setConsoleLines((current) => [...current.slice(-200), line])
  }

  const [lifeSection, setLifeSection] = useState("board")
  const [stageByProject, setStageByProject] = useState<Record<number, string>>({})

  function reloadProjects() {
    api.projects().then(setProjects).catch(() => setProjects([]))
    api.problems().then((rows) => {
      const map: Record<number, string> = {}
      for (const row of rows) if (row.project_id) map[row.project_id] = row.stage
      setStageByProject(map)
    }).catch(() => undefined)
  }

  useEffect(() => {
    if (user?.locale && user.locale !== i18n.language) void i18n.changeLanguage(user.locale)
    if (user?.theme === "light" || user?.theme === "dark" || user?.theme === "system") setTheme(user.theme)
  }, [user, i18n, setTheme])

  useEffect(() => {
    const onResize = () => setNarrow(window.innerWidth < 768)
    window.addEventListener("resize", onResize)
    return () => window.removeEventListener("resize", onResize)
  }, [])

  useEffect(() => {
    document.documentElement.classList.toggle("reduce-motion", localStorage.getItem("axiom_motion") === "reduce")
  }, [])

  useEffect(() => {
    saveLayout({
      leftWidth,
      rightWidth,
      bottomHeight,
      leftOpen: window.innerWidth >= 768 ? leftOpen : false,
      rightOpen,
      bottomOpen,
      doc,
      minimap,
    })
  }, [leftWidth, rightWidth, bottomHeight, leftOpen, rightOpen, bottomOpen, doc, minimap])

  useEffect(() => {
    if (!user) return
    reloadProjects()
    api.templates().then(setTemplates).catch(() => setTemplates([]))
    api.solvers().then(setSolvers).catch(() => setSolvers([]))
    api.algorithms().then(setAlgorithms).catch(() => undefined)
    api.translators().then((rows) => {
      const names = rows.map((item) => item.name)
      if (names.length) setTargets(names)
    }).catch(() => undefined)
    api.settings().then(setLlm).catch(() => undefined)
    const refreshLlm = () => { api.settings().then(setLlm).catch(() => undefined) }
    const refreshProblems = () => reloadProjects()
    window.addEventListener("axiom-settings", refreshLlm)
    window.addEventListener("axiom-lifecycle", refreshProblems)
    return () => {
      window.removeEventListener("axiom-settings", refreshLlm)
      window.removeEventListener("axiom-lifecycle", refreshProblems)
    }
  }, [user])

  useEffect(() => {
    if (!user) return
    let stop = false
    const tick = () => {
      api.problemNotices().then((notes) => {
        if (stop || notes.length === 0) return
        const chinese = i18n.language.startsWith("zh")
        for (const note of notes) void notifyFinished(chinese ? note.title : note.title_en || note.title, chinese ? note.body : note.body_en || note.body)
        void api.readProblemNotices(notes.map((note) => note.id))
      }).catch(() => undefined)
    }
    tick()
    const timer = window.setInterval(tick, 20000)
    return () => { stop = true; window.clearInterval(timer) }
  }, [user, i18n.language])

  useEffect(() => {
    if (!projectId || !user) return
    let stop = false
    setLoadError("")
    api.project(Number(projectId)).then((item) => {
      if (stop) return
      setTitle(item.title)
      setStatement(item.statement)
      restoring.current = true
      historyRef.current = historyStart(item.dsl)
      setDsl(item.dsl)
      window.setTimeout(() => { restoring.current = false }, 0)
      setSavedMark(`${item.title}\n${item.statement}\n${item.dsl}`)
      setDiagnostics([])
      setExpanded(item.id)
      const draft = loadDraft()
      if (draft && draftDiffers(draft, { projectId: item.id, title: item.title, statement: item.statement, dsl: item.dsl })) setRestore(draft)
      else setRestore(null)
    }).catch((reason: unknown) => setLoadError(reason instanceof ApiError ? reason.message : t("common.error")))
    api.versions(Number(projectId)).then(setVersions).catch(() => setVersions([]))
    api.runs(Number(projectId)).then((rows) => {
      if (stop) return
      setRuns(rows)
      setRun(rows[0] ?? null)
    }).catch(() => undefined)
    return () => {
      stop = true
    }
  }, [projectId, user, t])

  useEffect(() => {
    if (!runMatch?.params.id || !user) return
    let stop = false
    api.run(Number(runMatch.params.id)).then((item) => {
      if (stop) return
      setRun(item)
      setDoc("results")
      if (String(item.project_id) !== projectId) navigate(`/projects/${item.project_id}`)
    }).catch(() => undefined)
    return () => {
      stop = true
    }
  }, [runMatch?.params.id, user, navigate, projectId])

  const runId = run?.id
  const runStatus = run?.status
  useEffect(() => {
    if (!runId) return
    api.events(runId).then(setEvents).catch(() => undefined)
    if (!runStatus || !live.has(runStatus)) return
    const timer = window.setInterval(() => {
      api.run(runId).then((next) => {
        setRun(next)
        setRuns((current) => current.map((item) => (item.id === next.id ? next : item)))
      }).catch(() => undefined)
      api.events(runId).then(setEvents).catch(() => undefined)
    }, 400)
    return () => window.clearInterval(timer)
  }, [runId, runStatus])

  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      const meta = event.ctrlKey || event.metaKey
      if (meta && event.shiftKey && event.key.toLowerCase() === "p") {
        event.preventDefault()
        setPaletteOpen(true)
      } else if (meta && event.key.toLowerCase() === "k") {
        event.preventDefault()
        setPaletteOpen(true)
      } else if (meta && event.key.toLowerCase() === "s") {
        event.preventDefault()
        actions.current.save()
      } else if (meta && event.key.toLowerCase() === "n" && !event.shiftKey) {
        event.preventDefault()
        setNewOpen(true)
      } else if (meta && event.key.toLowerCase() === "b") {
        event.preventDefault()
        setLeftOpen((open) => !open)
      } else if (meta && event.key.toLowerCase() === "j") {
        event.preventDefault()
        setBottomOpen((open) => !open)
      } else if (event.key === "F5") {
        event.preventDefault()
        actions.current.solve()
      } else if (meta && event.key === "Enter") {
        event.preventDefault()
        actions.current.solve()
      } else if (meta && event.key.toLowerCase() === "g") {
        event.preventDefault()
        setGotoOpen(true)
      } else if (meta && event.key.toLowerCase() === "f") {
        event.preventDefault()
        setDoc("model")
        const view = editorRef.current?.view
        if (view) openSearchPanel(view)
      } else if (meta && event.altKey && event.key.toLowerCase() === "c") {
        event.preventDefault()
        actions.current.copyConclusion()
      } else if (meta && event.key === "/") {
        event.preventDefault()
        setShortcutsOpen(true)
      } else if (meta && !event.shiftKey && event.key.toLowerCase() === "z") {
        const target = event.target as HTMLElement | null
        if (target?.closest("[data-native-undo], .cm-editor")) return
        if (target?.closest("input, textarea") && !target.closest("[data-grid]")) return
        event.preventDefault()
        actions.current.undo()
      } else if (meta && (event.key.toLowerCase() === "y" || (event.shiftKey && event.key.toLowerCase() === "z"))) {
        const target = event.target as HTMLElement | null
        if (target?.closest("[data-native-undo], .cm-editor")) return
        if (target?.closest("input, textarea") && !target.closest("[data-grid]")) return
        event.preventDefault()
        actions.current.redo()
      }
    }
    window.addEventListener("keydown", onKey)
    return () => window.removeEventListener("keydown", onKey)
  })

  useEffect(() => {
    function close() {
      setMenu(null)
    }
    window.addEventListener("click", close)
    return () => window.removeEventListener("click", close)
  }, [])

  useEffect(() => {
    if (!projectId || !dsl.trim()) return
    const timer = window.setTimeout(() => {
      api.validate(dsl).then((result) => setDiagnostics(result.diagnostics || [])).catch(() => undefined)
    }, 450)
    return () => window.clearTimeout(timer)
  }, [dsl, projectId])

  useEffect(() => {
    if (!projectId) return
    if (!dsl.trim()) {
      setEquations(null)
      setEquationState("empty")
      return
    }
    let alive = true
    setEquationState((current) => (current === "ready" ? current : "loading"))
    const timer = window.setTimeout(() => {
      api.standardForm(dsl).then((form) => {
        if (!alive) return
        setEquations(form)
        setEquationState(form.ok ? "ready" : "error")
      }).catch(() => {
        if (!alive) return
        setEquations({ ok: false, message: "标准方程没有生成。", message_en: "Standard equations were not generated." })
        setEquationState("error")
      })
    }, 450)
    return () => {
      alive = false
      window.clearTimeout(timer)
    }
  }, [dsl, projectId])

  useEffect(() => {
    if (!run?.dsl || dsl.trim()) return
    setDsl(run.dsl)
    setSavedMark(`${title}\n${statement}\n${run.dsl}`)
  }, [run?.dsl, dsl, title, statement])

  useEffect(() => {
    if (!dsl.trim()) {
      setAdvice(null)
      return
    }
    const timer = window.setTimeout(() => {
      api.recommend(dsl).then(setAdvice).catch(() => undefined)
    }, 500)
    return () => window.clearTimeout(timer)
  }, [dsl])

  useEffect(() => {
    const unsaved = Boolean(projectId) && savedMark !== "" && `${title}\n${statement}\n${dsl}` !== savedMark
    if (!unsaved) return
    const draft = { projectId: Number(projectId), title, statement, dsl, auto, solver, algorithm, savedAt: new Date().toISOString() }
    const timer = window.setTimeout(() => saveDraft(draft), 800)
    function flush() {
      saveDraft(draft)
    }
    window.addEventListener("pagehide", flush)
    return () => {
      window.clearTimeout(timer)
      window.removeEventListener("pagehide", flush)
    }
  }, [projectId, savedMark, title, statement, dsl, auto, solver, algorithm])

  useEffect(() => {
    if (!run) return
    const key = `${run.id}:${run.status}`
    if (seenRun.current === null || !seenRun.current.startsWith(`${run.id}:`)) {
      seenRun.current = key
      return
    }
    if (seenRun.current === key) return
    seenRun.current = key
    if (run.status !== "completed" && run.status !== "failed") return
    const titleText = title || t("product")
    void notifyFinished(titleText, run.status === "completed" ? t("ide.solvedBanner") : (zh ? run.error : run.error_en || run.error))
  }, [run, title, t, zh])

  useEffect(() => {
    if (!celebrate || run?.status !== "completed" || celebrated.current) return
    celebrated.current = true
    toast.success(t("ide.solvedBanner"))
  }, [celebrate, run?.status, t])

  async function save() {
    if (!projectId) return
    const next = await api.updateProject(Number(projectId), { title, statement, dsl })
    setProjects((current) => (current || []).map((item) => (item.id === next.id ? next : item)))
    setSavedMark(`${title}\n${statement}\n${dsl}`)
    clearDraft()
    log(t("studio.saved"))
    toast.success(t("ide.savedFlash"))
  }

  async function solve() {
    if (!projectId) return
    try {
      if (dsl.trim()) {
        const form = await api.standardForm(dsl)
        setEquations(form)
        setEquationState(form.ok ? "ready" : "error")
        if (!form.ok) {
          setDoc("equations")
          toast.error(zh ? form.message || t("studio.invalid") : form.message_en || form.message || t("studio.invalid"))
          return
        }
      }
      await save()
      const started = await api.startRun(Number(projectId), {
        statement,
        dsl,
        solver,
        algorithm,
        auto_approve: auto,
        locale: zh ? "zh-CN" : "en",
      })
      setRun(started)
      setEvents([])
      setBottomOpen(true)
      setBottomTab("agents")
      log(`${t("studio.started")} #${started.id}`)
      toast.success(t("studio.started"))
      api.versions(Number(projectId)).then(setVersions).catch(() => undefined)
    } catch (reason) {
      const message = reason instanceof ApiError ? (zh ? reason.message : reason.messageEn) : t("common.error")
      log(message)
      toast.error(message)
    }
  }

  async function stop() {
    if (!run) return
    try {
      const next = await api.cancelRun(run.id)
      setRun(next)
      log(zh ? "已停止" : "Stopped")
    } catch (reason) {
      toast.error(reason instanceof ApiError ? (zh ? reason.message : reason.messageEn) : t("common.error"))
    }
  }

  async function decide(decision: "approved" | "rejected") {
    if (!run) return
    const next = await api.decide(run.id, decision)
    setRun(next)
  }

  async function validateModel() {
    const result = await api.validate(dsl)
    const found = result.diagnostics || []
    setDiagnostics(found)
    if (result.ok) {
      if (result.aml) commitDsl(result.aml)
      toast.success(t("studio.valid"))
      log(t("studio.valid"))
    } else {
      setDoc("model")
      setBottomOpen(true)
      setBottomTab("diagnostics")
      const first = found[0]
      toast.error(zh ? first?.message : first?.message_en)
    }
  }

  function jumpDiagnostic(line: number | undefined) {
    setDoc("model")
    window.setTimeout(() => revealLine(editorRef.current?.view, line || 1), 0)
  }

  async function doImport(file: File) {
    const text = await file.text()
    const lower = file.name.toLowerCase()
    if (lower.endsWith(".aml") || lower.endsWith(".axiom")) {
      commitDsl(text)
      setDoc("model")
      toast.success(t("studio.model"))
      return
    }
    const format = formatOf(lower) || "lp"
    const imported = await api.importModel(format, text)
    commitDsl(imported.aml)
    setDoc("model")
    toast.success(imported.ok ? t("studio.valid") : t("studio.invalid"))
  }

  async function exportModel() {
    const source = dsl || run?.dsl || ""
    setExporting(true)
    try {
      const translated = await api.translate(source, target)
      setExportCode(translated.code)
      setDoc("export")
      toast.success(t("studio.export"))
    } catch (reason) {
      toast.error(reason instanceof ApiError ? (zh ? reason.message : reason.messageEn) : t("common.error"))
    } finally {
      setExporting(false)
    }
  }

  function commitDsl(next: string) {
    if (!restoring.current) historyRef.current = historyPush(historyRef.current, next)
    restoring.current = true
    setDsl(next)
    window.setTimeout(() => { restoring.current = false }, 0)
  }

  function onEditorChange(value: string) {
    setDsl(value)
    window.clearTimeout(snapTimer.current)
    snapTimer.current = window.setTimeout(() => {
      if (restoring.current) return
      historyRef.current = historyPush(historyRef.current, value)
    }, 500)
  }

  function undoModel() {
    const active = document.activeElement as HTMLElement | null
    if (active?.closest(".cm-editor")) {
      const view = editorRef.current?.view
      if (view) undo(view)
      return
    }
    const next = historyUndo(historyRef.current)
    if (next !== historyRef.current) {
      historyRef.current = next
      restoring.current = true
      setDsl(next.present)
      window.setTimeout(() => { restoring.current = false }, 0)
      return
    }
    const view = editorRef.current?.view
    if (view) undo(view)
  }

  function redoModel() {
    const active = document.activeElement as HTMLElement | null
    if (active?.closest(".cm-editor")) {
      const view = editorRef.current?.view
      if (view) redo(view)
      return
    }
    const next = historyRedo(historyRef.current)
    if (next !== historyRef.current) {
      historyRef.current = next
      restoring.current = true
      setDsl(next.present)
      window.setTimeout(() => { restoring.current = false }, 0)
      return
    }
    const view = editorRef.current?.view
    if (view) redo(view)
  }

  function jumpConstraint(name: string) {
    setEquationFocus(name)
    setDoc("equations")
    setBottomOpen(true)
    setBottomTab("diagnostics")
  }

  function openTable(file: File) {
    const name = file.name.toLowerCase()
    if (name.endsWith(".csv") || name.endsWith(".xlsx") || name.endsWith(".xlsm")) {
      setWizardFile(file)
      return
    }
    if (name.endsWith(".aml") || name.endsWith(".axiom")) {
      void file.text().then((text) => {
        commitDsl(text)
        setDoc("model")
        toast.success(t("studio.model"))
      })
      return
    }
    if (formatOf(name)) void doImport(file)
  }

  function copyConclusion() {
    const result = run?.result
    if (!result || (result.objective == null && !result.variables)) {
      toast.error(zh ? "还没有可以复制的结论。" : "There is no conclusion to copy yet.")
      return
    }
    const text = executiveSummary({
      title: result.title || result.formulation?.title || title,
      solver: run?.solver || result.solver,
      status: result.status || run?.status,
      objective: result.objective ?? (run?.objective ? Number(run.objective) : null),
      variables: result.variables,
      constraints: result.constraints,
    }, zh)
    void copyText(text).then(() => toast.success(t("results.copied")))
  }

  async function saveVersion() {
    if (!projectId) return
    const row = await api.saveVersion(Number(projectId), { label: zh ? "手动保存" : "Manual save", dsl, statement })
    setVersions((current) => [row, ...current])
    toast.success(t("ux.versionSaved"))
  }

  function rollback(version: VersionRow) {
    commitDsl(version.dsl)
    setStatement(version.statement || statement)
    setDoc("model")
    toast.success(t("ux.rolled"))
  }

  actions.current = { save: () => void save(), solve: () => void solve(), validate: () => void validateModel(), undo: () => undoModel(), redo: () => redoModel(), copyConclusion: () => copyConclusion() }

  async function createProject(event: FormEvent) {
    event.preventDefault()
    const created = await api.createProject({ title: newTitle, statement: newStatement, locale: zh ? "zh-CN" : "en" })
    setNewOpen(false)
    setNewTitle("")
    setNewStatement("")
    reloadProjects()
    navigate(`/projects/${created.id}`)
    setDoc("problem")
  }

  async function createFromTemplate(item: TemplateInfo) {
    const full = await api.template(item.id)
    const created = await api.createProject({
      title: zh ? full.title_zh : full.title_en,
      statement: zh ? full.summary_zh : full.summary_en,
      dsl: full.dsl || "",
      locale: zh ? "zh-CN" : "en",
    })
    reloadProjects()
    navigate(`/projects/${created.id}`)
    setDoc("model")
    setSide("explorer")
  }

  async function removeProject(id: number) {
    const snapshot = (projects || []).find((item) => item.id === id)
    await api.deleteProject(id)
    reloadProjects()
    if (String(id) === projectId) navigate("/")
    toast(t("ide.deleted"), {
      action: snapshot
        ? {
            label: t("ide.undoDelete"),
            onClick: () => {
              void api.createProject({
                title: snapshot.title,
                statement: snapshot.statement,
                dsl: snapshot.dsl,
                locale: snapshot.locale,
              }).then(() => reloadProjects())
            },
          }
        : undefined,
    })
  }

  async function solveTemplate(item: TemplateInfo) {
    const full = await api.template(item.id)
    const created = await api.createProject({
      title: zh ? full.title_zh : full.title_en,
      statement: zh ? full.summary_zh : full.summary_en,
      dsl: full.dsl || "",
      locale: zh ? "zh-CN" : "en",
    })
    const started = await api.startRun(created.id, {
      statement: zh ? full.summary_zh : full.summary_en,
      dsl: full.dsl || "",
      solver,
      algorithm,
      auto_approve: true,
      locale: zh ? "zh-CN" : "en",
    })
    celebrated.current = false
    setCelebrate(true)
    setRun(started)
    setRuns([started])
    setEvents([])
    setDoc("results")
    setBottomOpen(true)
    setBottomTab("agents")
    reloadProjects()
    navigate(`/projects/${created.id}`)
    toast.success(t("studio.started"))
  }

  function dismissTour() {
    localStorage.setItem("axiom.tour", "done")
    setTourOn(false)
  }

  async function makeProblem() {
    const text = chatDraft.trim() || statement.trim()
    if (!text) return
    try {
      const created = await api.createProblem({
        title: text.slice(0, 40),
        description: text,
        project_id: projectId ? Number(projectId) : undefined,
        dsl,
        fill_existing: true,
      })
      setDoc("lifecycle")
      setLifeSection("overview")
      reloadProjects()
      if (created.project_id) navigate(`/projects/${created.project_id}`)
      toast.success(created.title)
    } catch (reason) {
      toast.error(reason instanceof ApiError ? (zh ? reason.message : reason.messageEn) : t("common.error"))
    }
  }

  async function sendChat() {
    const content = chatDraft.trim()
    if (!content || chatPending) return
    const next = [...chat, { role: "user", content }]
    setChat(next)
    setChatDraft("")
    setChatPending(true)
    try {
      const reply = await api.chat([
        { role: "system", content: `问题：${statement}\n\nAML:\n${dsl.slice(0, 6000)}` },
        ...next,
      ], projectId ? Number(projectId) : undefined)
      setChat((current) => [...current, { role: "assistant", content: reply.content }])
      if (reply.lifecycle) {
        setDoc("lifecycle")
        setLifeSection("overview")
        reloadProjects()
        if (reply.lifecycle.project_id) navigate(`/projects/${reply.lifecycle.project_id}`)
        void notifyFinished(zh ? "生命周期已更新" : "Lifecycle updated", reply.lifecycle.title)
      }
      if (reply.proposals?.length) setAnalysisProposals(reply.proposals)
      if (reply.study) {
        setAnalysisSeed({ token: Date.now(), study: reply.study })
        setDoc("analysis")
      }
    } catch (reason) {
      const message = reason instanceof ApiError ? (zh ? reason.message : reason.messageEn) : t("common.error")
      toast.error(message)
      setChat((current) => [...current, { role: "assistant", content: message }])
    } finally {
      setChatPending(false)
    }
  }

  async function switchLocale(next: string) {
    await i18n.changeLanguage(next)
    localStorage.setItem("axiom_locale", next)
    if (user) {
      const updated = await api.updateMe({ locale: next })
      refresh(updated)
    }
  }

  async function switchTheme(next: "light" | "dark") {
    setTheme(next)
    if (user) {
      const updated = await api.updateMe({ theme: next })
      refresh(updated)
    }
  }

  function toggleMotion() {
    const next = localStorage.getItem("axiom_motion") === "reduce" ? "full" : "reduce"
    localStorage.setItem("axiom_motion", next)
    document.documentElement.classList.toggle("reduce-motion", next === "reduce")
    toast.success(t("ide.motion"))
  }

  function windowAction(action: "minimize" | "maximize" | "close") {
    const desktop = window.axiom?.window
    if (desktop) {
      desktop[action]()
      return
    }
    if (action === "maximize") {
      if (document.fullscreenElement) void document.exitFullscreen()
      else void document.documentElement.requestFullscreen().catch(() => undefined)
    }
    if (action === "close") void logout()
  }

  function dragWidth(event: ReactMouseEvent, start: number, set: (value: number) => void, min: number, max: number, node: HTMLElement | null, invert = false) {
    event.preventDefault()
    const origin = event.clientX
    let next = start
    let frame = 0
    document.documentElement.classList.add("app-resizing")
    function apply(value: number) {
      if (node) node.style.width = `${value}px`
    }
    function move(native: MouseEvent) {
      next = Math.min(max, Math.max(min, start + (invert ? origin - native.clientX : native.clientX - origin)))
      if (frame) return
      frame = window.requestAnimationFrame(() => {
        frame = 0
        apply(next)
      })
    }
    function up() {
      if (frame) window.cancelAnimationFrame(frame)
      apply(next)
      set(next)
      document.documentElement.classList.remove("app-resizing")
      window.removeEventListener("mousemove", move)
      window.removeEventListener("mouseup", up)
    }
    window.addEventListener("mousemove", move)
    window.addEventListener("mouseup", up)
  }

  function dragHeight(event: ReactMouseEvent) {
    event.preventDefault()
    const origin = event.clientY
    const start = bottomHeight
    let next = start
    let frame = 0
    const node = bottomPanelRef.current
    document.documentElement.classList.add("app-resizing")
    function move(native: MouseEvent) {
      next = Math.min(420, Math.max(96, start + (origin - native.clientY)))
      if (frame) return
      frame = window.requestAnimationFrame(() => {
        frame = 0
        if (node) node.style.height = `${next}px`
      })
    }
    function up() {
      if (frame) window.cancelAnimationFrame(frame)
      if (node) node.style.height = `${next}px`
      setBottomHeight(next)
      document.documentElement.classList.remove("app-resizing")
      window.removeEventListener("mousemove", move)
      window.removeEventListener("mouseup", up)
    }
    window.addEventListener("mousemove", move)
    window.addEventListener("mouseup", up)
  }

  const running = run ? live.has(run.status) : false
  const docTitle = title || t("product")
  const questions = run?.result?.questions || run?.result?.formulation?.questions || []
  const solverEvents = events.filter((item) => item.agent === "solver" || item.kind === "race")

  const both = (zhLabel: string, enLabel: string) => (zh ? `${zhLabel}    ${enLabel}` : `${enLabel}    ${zhLabel}`)
  const commands = [
    { label: both("新建问题", "New problem"), shortcut: "Ctrl+N", run: () => setNewOpen(true) },
    { label: both("保存", "Save"), shortcut: "Ctrl+S", run: () => void save() },
    { label: both("开始求解", "Start solve"), shortcut: "F5", run: () => void solve() },
    { label: both("问题生命周期", "Problem lifecycle"), run: () => { setDoc("lifecycle"); setLifeSection("board") } },
    { label: both("复制结论", "Copy conclusion"), shortcut: "Ctrl+Alt+C", run: () => copyConclusion() },
    { label: both("结果", "Results"), run: () => setDoc("results") },
    { label: both("导出 PDF", "Export PDF"), run: () => { if (run) void downloadReport(run.id, "pdf", i18n.language) } },
    { label: both("审计日志", "Audit log"), run: () => navigate("/audit") },
    { label: both("工作区", "Workspaces"), run: () => navigate("/workspaces") },
    { label: both("停止", "Stop"), run: () => void stop() },
    { label: both("校验模型", "Validate model"), run: () => void validateModel() },
    { label: both("标准方程", "Standard equations"), run: () => setDoc("equations") },
    { label: both("导入数据", "Import data"), run: () => dataRef.current?.click() },
    { label: both("行业模板", "Industry templates"), run: () => setGalleryOpen(true) },
    { label: both("假设分析", "What-if"), run: () => setDoc("results") },
    { label: both("分析工作台", "Analysis workbench"), run: () => setDoc("analysis") },
    { label: both("兼容性矩阵", "Compatibility matrix"), run: () => setCompatOpen(true) },
    { label: both("试验设计", "Design of experiments"), run: () => { setAnalysisFocus("doe"); setDoc("analysis") } },
    { label: both("多学科优化", "Multidisciplinary optimization"), run: () => { setAnalysisFocus("mdo"); setDoc("analysis") } },
    { label: both("查找替换", "Find and replace"), shortcut: "Ctrl+F", run: () => { setDoc("model"); const view = editorRef.current?.view; if (view) openSearchPanel(view) } },
    { label: both("转到行", "Go to line"), shortcut: "Ctrl+G", run: () => setGotoOpen(true) },
    { label: both("资源管理器", "Explorer"), shortcut: "Ctrl+B", run: () => setLeftOpen((open) => !open) },
    { label: both("底部面板", "Bottom panel"), shortcut: "Ctrl+J", run: () => setBottomOpen((open) => !open) },
    { label: both("对话", "Chat"), run: () => { setRightOpen(true); setRightTab("chat") } },
    { label: both("设置", "Settings"), run: () => navigate("/settings") },
    { label: both("模板", "Templates"), run: () => { setLeftOpen(true); setSide("templates") } },
    { label: both("深色主题", "Dark theme"), run: () => void switchTheme("dark") },
    { label: both("浅色主题", "Light theme"), run: () => void switchTheme("light") },
    { label: both("缩略图", "Minimap"), run: () => setMinimap((value) => !value) },
    { label: both("减少动效", "Reduce motion"), run: () => toggleMotion() },
    { label: both("自动批准", "Auto-approve"), run: () => setAuto((value) => !value) },
    { label: both("键盘快捷键", "Keyboard shortcuts"), shortcut: "Ctrl+/", run: () => setShortcutsOpen(true) },
  ]
  const fingerprint = `${title}\n${statement}\n${dsl}`
  const dirty = Boolean(projectId) && savedMark !== "" && fingerprint !== savedMark
  const solveReason = !projectId ? t("ide.needProject") : running ? t("ide.alreadyRunning") : ""

  return (
    <div className="flex h-dvh flex-col bg-background text-[13px] text-foreground">
      <header className="app-caption titlebar-drag flex shrink-0 items-center">
        <img src="/favicon.svg" alt="" className="no-drag ml-2 size-5" />
        <div className="no-drag ml-2 font-medium">{t("product")}</div>
        <div className="min-w-0 flex-1 truncate px-3 text-center opacity-80">{docTitle}</div>
        <Button variant="ghost" size="icon-sm" className="no-drag rounded-none md:hidden" aria-label="menu" onClick={() => { setLeftOpen(true); setSide("explorer") }}>
          <FolderOpen />
        </Button>
        <div className="no-drag flex h-full">
          <button type="button" className="h-full w-11 hover:bg-black/10 dark:hover:bg-white/10" aria-label={t("ide.minimize")} onClick={() => windowAction("minimize")}>—</button>
          <button type="button" className="h-full w-11 hover:bg-black/10 dark:hover:bg-white/10" aria-label={t("ide.maximize")} onClick={() => windowAction("maximize")}>□</button>
          <button type="button" className="h-full w-11 hover:bg-red-600 hover:text-white" aria-label={t("ide.close")} onClick={() => windowAction("close")}>×</button>
        </div>
      </header>
      <SidecarBanner />

      <div className="app-menubar no-drag flex shrink-0 items-center px-1">
        <Menu label={t("ide.file")}>
          <DropdownMenuItem onClick={() => setNewOpen(true)}>{t("ide.new")}<DropdownMenuShortcut>Ctrl+N</DropdownMenuShortcut></DropdownMenuItem>
          <DropdownMenuItem onClick={() => { setLeftOpen(true); setSide("explorer") }}>{t("ide.open")}<DropdownMenuShortcut>Ctrl+O</DropdownMenuShortcut></DropdownMenuItem>
          <DropdownMenuItem onClick={() => void save()}>{t("ide.save")}<DropdownMenuShortcut>Ctrl+S</DropdownMenuShortcut></DropdownMenuItem>
          <DropdownMenuSeparator />
          <DropdownMenuItem onClick={() => navigate("/templates")}>{t("ide.fromTemplate")}</DropdownMenuItem>
          <DropdownMenuItem onClick={() => setGalleryOpen(true)}>{t("ux.gallery")}</DropdownMenuItem>
          <DropdownMenuItem onClick={() => importRef.current?.click()}>{t("ide.importLp")}</DropdownMenuItem>
          <DropdownMenuItem onClick={() => mathRef.current?.click()}>{t("ide.importMath")}</DropdownMenuItem>
          <DropdownMenuItem onClick={() => dataRef.current?.click()}>{t("ux.importData")}</DropdownMenuItem>
          <DropdownMenuItem disabled={!run} onClick={() => run && void downloadReport(run.id, "pdf", i18n.language)}>{t("ide.exportReport")}</DropdownMenuItem>
          <DropdownMenuItem disabled={!run} onClick={() => run && void downloadPackage(run.id, i18n.language)}>{t("ux.package")}</DropdownMenuItem>
          <DropdownMenuSeparator />
          <DropdownMenuItem onClick={() => void logout()}>{t("common.signOut")}</DropdownMenuItem>
        </Menu>
        <Menu label={t("ide.edit")}>
          <DropdownMenuItem onClick={() => undoModel()}>{t("ide.undo")}<DropdownMenuShortcut>Ctrl+Z</DropdownMenuShortcut></DropdownMenuItem>
          <DropdownMenuItem onClick={() => redoModel()}>{t("ide.redo")}<DropdownMenuShortcut>Ctrl+Y</DropdownMenuShortcut></DropdownMenuItem>
          <DropdownMenuItem onClick={() => { setDoc("model"); const view = editorRef.current?.view; if (view) openSearchPanel(view) }}>{t("ide.find")}<DropdownMenuShortcut>Ctrl+F</DropdownMenuShortcut></DropdownMenuItem>
          <DropdownMenuItem onClick={() => setGotoOpen(true)}>{t("ide.goto")}<DropdownMenuShortcut>Ctrl+G</DropdownMenuShortcut></DropdownMenuItem>
          <DropdownMenuSeparator />
          <DropdownMenuItem onClick={() => setPaletteOpen(true)}>{t("ide.palette")}<DropdownMenuShortcut>Ctrl+Shift+P</DropdownMenuShortcut></DropdownMenuItem>
        </Menu>
        <Menu label={t("ide.view")}>
          <DropdownMenuItem onClick={() => setLeftOpen((open) => !open)}>{t("ide.explorer")}<DropdownMenuShortcut>Ctrl+B</DropdownMenuShortcut></DropdownMenuItem>
          <DropdownMenuItem onClick={() => setBottomOpen((open) => !open)}>{t("ide.bottom")}<DropdownMenuShortcut>Ctrl+J</DropdownMenuShortcut></DropdownMenuItem>
          <DropdownMenuItem onClick={() => setMinimap((value) => !value)}>{t("ide.minimap")}</DropdownMenuItem>
          <DropdownMenuItem onClick={() => toggleMotion()}>{t("ide.motion")}</DropdownMenuItem>
          <DropdownMenuItem onClick={() => { setRightOpen(true); setRightTab("inspector") }}>{t("ide.inspector")}</DropdownMenuItem>
          <DropdownMenuItem onClick={() => { setRightOpen(true); setRightTab("chat") }}>{t("ide.chat")}</DropdownMenuItem>
          <DropdownMenuItem onClick={() => { setDoc("lifecycle"); setLifeSection("board") }}>{t("lifecycle.tab")}</DropdownMenuItem>
          <DropdownMenuItem onClick={() => navigate("/gallery")}>{t("figures.gallery")}</DropdownMenuItem>
          <DropdownMenuSeparator />
          <DropdownMenuItem onClick={() => void switchTheme(resolvedTheme === "dark" ? "light" : "dark")}>{resolvedTheme === "dark" ? t("ide.themeLight") : t("ide.themeDark")}</DropdownMenuItem>
          <DropdownMenuItem onClick={() => void switchLocale(zh ? "en" : "zh-CN")}>{zh ? "English" : "中文"}</DropdownMenuItem>
        </Menu>
        <Menu label={t("ide.model")}>
          <DropdownMenuItem onClick={() => setDoc("problem")}>{t("studio.problem")}</DropdownMenuItem>
          <DropdownMenuItem onClick={() => setDoc("model")}>{t("studio.model")}</DropdownMenuItem>
          <DropdownMenuItem onClick={() => setDoc("data")}>{t("ide.data")}</DropdownMenuItem>
          <DropdownMenuItem onClick={() => setDoc("equations")}>{t("studio.equations")}</DropdownMenuItem>
          <DropdownMenuItem onClick={() => void validateModel()}>{t("ide.validate")}</DropdownMenuItem>
          <DropdownMenuItem onClick={() => setDoc("export")}>{t("studio.export")}</DropdownMenuItem>
        </Menu>
        <Menu label={t("ide.solveMenu")}>
          <DropdownMenuItem onClick={() => void solve()}>{t("ide.run")}<DropdownMenuShortcut>F5</DropdownMenuShortcut></DropdownMenuItem>
          <DropdownMenuItem disabled={!running} onClick={() => void stop()}>{t("ide.stop")}</DropdownMenuItem>
          <DropdownMenuItem onClick={() => setAuto((value) => !value)}>{t("studio.auto")}</DropdownMenuItem>
          <DropdownMenuSub>
            <DropdownMenuSubTrigger>{t("studio.solver")}</DropdownMenuSubTrigger>
            <DropdownMenuSubContent>
              {solvers.filter((item) => item.available).map((item) => (
                <DropdownMenuItem key={item.name} onClick={() => setSolver(item.name)}>{item.label}</DropdownMenuItem>
              ))}
            </DropdownMenuSubContent>
          </DropdownMenuSub>
        </Menu>
        <Menu label={t("ide.analysis")}>
          <DropdownMenuItem onClick={() => setDoc("analysis")}>{t("analysis.workbench")}</DropdownMenuItem>
          <DropdownMenuItem onClick={() => { setAnalysisFocus("doe"); setDoc("analysis") }}>{t("analysis.doe")}</DropdownMenuItem>
          <DropdownMenuItem onClick={() => { setAnalysisFocus("sensitivity"); setDoc("analysis") }}>{t("analysis.sensitivity")}</DropdownMenuItem>
          <DropdownMenuItem onClick={() => { setAnalysisFocus("uq"); setDoc("analysis") }}>{t("analysis.uq")}</DropdownMenuItem>
          <DropdownMenuItem onClick={() => { setAnalysisFocus("mdo"); setDoc("analysis") }}>{t("analysis.mdo")}</DropdownMenuItem>
          <DropdownMenuItem onClick={() => { setAnalysisFocus("multi"); setDoc("analysis") }}>{t("analysis.multi")}</DropdownMenuItem>
          <DropdownMenuSeparator />
          <DropdownMenuItem onClick={() => setDoc("results")}>{t("ux.whatif")}</DropdownMenuItem>
          <DropdownMenuItem onClick={() => setDoc("results")}>{t("results.sensitivity")}</DropdownMenuItem>
          <DropdownMenuItem onClick={() => setDoc("results")}>{t("results.scenarios")}</DropdownMenuItem>
          <DropdownMenuItem onClick={() => setDoc("results")}>{t("results.monte")}</DropdownMenuItem>
          <DropdownMenuItem onClick={() => setDoc("results")}>{t("results.simulation")}</DropdownMenuItem>
        </Menu>
        <Menu label={t("ide.agents")}>
          <DropdownMenuItem onClick={() => { setBottomOpen(true); setBottomTab("agents") }}>{t("ide.log")}</DropdownMenuItem>
          <DropdownMenuItem disabled={!run?.pending_gate} onClick={() => void decide("approved")}>{t("ide.approve")}</DropdownMenuItem>
          <DropdownMenuItem disabled={!run?.pending_gate} onClick={() => void decide("rejected")}>{t("ide.reject")}</DropdownMenuItem>
        </Menu>
        <Menu label={t("ide.tools")}>
          <DropdownMenuItem onClick={() => navigate("/settings")}>{t("ide.settings")}</DropdownMenuItem>
          <DropdownMenuItem onClick={() => navigate("/workspaces")}>{t("nav.workspaces")}</DropdownMenuItem>
          <DropdownMenuItem onClick={() => navigate("/audit")}>{t("nav.audit")}</DropdownMenuItem>
          <DropdownMenuItem onClick={() => void api.testLlm().then((result) => toast[result.ok ? "success" : "error"](zh ? result.message : result.message_en))}>{t("ide.testLlm")}</DropdownMenuItem>
        </Menu>
        <Menu label={t("ide.help")}>
          <DropdownMenuItem onClick={() => setShortcutsOpen(true)}>{t("ide.shortcuts")}<DropdownMenuShortcut>Ctrl+/</DropdownMenuShortcut></DropdownMenuItem>
          <DropdownMenuItem onClick={() => setCompatOpen(true)}>{t("analysis.compatibility")}</DropdownMenuItem>
          <DropdownMenuItem onClick={() => setAboutOpen(true)}>{t("ide.about")}</DropdownMenuItem>
        </Menu>
      </div>

      <div className="app-toolbar no-drag shrink-0">
        <ToolButton labeled label={t("ide.new")} onClick={() => setNewOpen(true)}><FilePlus /></ToolButton>
        <ToolButton labeled label={t("ide.open")} onClick={() => { setLeftOpen(true); setSide("explorer") }}><FolderOpen /></ToolButton>
        <ToolButton labeled label={t("ide.save")} onClick={() => void save()}><Save /></ToolButton>
        <span className="mx-1 h-5 w-px bg-border" />
        <ToolButton labeled primary label={t("ide.run")} disabled={Boolean(solveReason)} title={solveReason || t("ide.run")} onClick={() => void solve()}><Play /></ToolButton>
        <ToolButton labeled label={t("ide.stop")} onClick={() => void stop()} disabled={!running}><Square /></ToolButton>
        <ToolButton labeled label={t("ide.approve")} onClick={() => void decide("approved")} disabled={!run?.pending_gate}><Check /></ToolButton>
        <ToolButton labeled label={t("studio.export")} onClick={() => void exportModel()}><Download /></ToolButton>
        <ToolButton labeled label={t("ide.analysis")} onClick={() => setDoc("analysis")}><LineChart /></ToolButton>
        <Select value={solver} onValueChange={setSolver}>
          <SelectTrigger className="ml-1 h-7 w-28 text-xs"><SelectValue /></SelectTrigger>
          <SelectContent>
            {solvers.filter((item) => item.available).map((item) => (
              <SelectItem key={item.name} value={item.name}>{item.label}</SelectItem>
            ))}
          </SelectContent>
        </Select>
        <Select value={algorithm} onValueChange={(id) => {
          setAlgorithm(id)
          const chosen = algorithms.find((item) => item.id === id)
          if (chosen && id !== "auto") setSolver(chosen.solver)
        }}>
          <SelectTrigger data-algorithm className="ml-1 h-7 w-44 text-xs"><SelectValue /></SelectTrigger>
          <SelectContent>
            {algorithms.map((item) => (
              <SelectItem key={item.id} value={item.id}>{zh ? item.label_zh : item.label_en}</SelectItem>
            ))}
          </SelectContent>
        </Select>
        <label className="ml-2 flex items-center gap-1 text-[12px]">
          <Switch checked={auto} onCheckedChange={setAuto} aria-label={t("ide.autoShort")} />
          {t("ide.autoShort")}
        </label>
      </div>

      <div className="flex min-h-0 flex-1">
        <nav className="app-activity flex shrink-0 flex-col items-center gap-0.5 py-1" aria-label={t("ide.explorer")}>
          <ToolButton label={t("ide.explorer")} pressed={side === "explorer" && leftOpen} onClick={() => { setSide("explorer"); setLeftOpen(true) }}><FolderOpen /></ToolButton>
          <ToolButton label={t("nav.templates")} pressed={side === "templates" && leftOpen} onClick={() => { setSide("templates"); setLeftOpen(true) }}><Library /></ToolButton>
          <ToolButton label={t("ide.log")} pressed={bottomOpen && bottomTab === "agents"} onClick={() => { setBottomOpen(true); setBottomTab("agents") }}><Bot /></ToolButton>
          <ToolButton label={t("ide.chat")} pressed={rightOpen && rightTab === "chat"} onClick={() => { setRightOpen(true); setRightTab("chat") }}><MessageSquare /></ToolButton>
          <ToolButton label={t("ide.bottom")} pressed={bottomOpen} onClick={() => setBottomOpen((open) => !open)}><PanelBottom /></ToolButton>
          <div className="mt-auto">
            <ToolButton label={t("ide.settings")} onClick={() => navigate("/settings")}><Settings /></ToolButton>
          </div>
        </nav>

        {leftOpen ? (
          <aside
            ref={leftPanelRef}
            data-panel="explorer"
            className={narrow ? "app-float left-10 flex w-64 flex-col border-r bg-sidebar text-sidebar-foreground shadow-md" : "flex shrink-0 flex-col border-r bg-sidebar text-sidebar-foreground"}
            style={narrow ? undefined : { width: leftWidth }}
          >
            <div className="flex h-7 items-center px-2 text-[11px] font-medium tracking-wide text-sidebar-foreground/70 uppercase">
              {side === "templates" ? t("templates.title") : t("nav.projects")}
            </div>
            {side === "explorer" ? (
              <div className="min-h-0 flex-1 overflow-auto px-1 pb-2 text-[12px]">
                {projects === null ? <div className="app-skeleton" data-loading="projects" /> : null}
                {projects !== null && projects.length === 0 ? (
                  <div className="px-2 py-2 text-sidebar-foreground/60">
                    <p>{t("ide.emptyExplorer")}</p>
                    <button type="button" className="mt-1 text-sidebar-primary" onClick={() => setNewOpen(true)}>{t("ide.emptyNext")}</button>
                  </div>
                ) : null}
                {(projects || []).map((project) => {
                  const open = expanded === project.id
                  return (
                    <div key={project.id}>
                      <button
                        type="button"
                        title={project.title}
                        className="flex w-full items-center gap-1 rounded px-1 py-0.5 text-left hover:bg-sidebar-accent"
                        onClick={() => {
                          setExpanded(open ? null : project.id)
                          navigate(`/projects/${project.id}`)
                        }}
                        onContextMenu={(event) => {
                          event.preventDefault()
                          setMenu({ x: event.clientX, y: event.clientY, id: project.id })
                        }}
                      >
                        {open ? <ChevronDown className="size-3" /> : <ChevronRight className="size-3" />}
                        <span className="truncate">{project.title}</span>
                        {stageByProject[project.id] ? <span className="ml-auto shrink-0 rounded bg-sidebar-accent px-1 text-[10px]">{t(`lifecycle.stage.${stageByProject[project.id]}`, { defaultValue: stageByProject[project.id] })}</span> : null}
                      </button>
                      {open ? (
                        <div className="ml-4 border-l border-sidebar-border pl-1">
                          <TreeButton onClick={() => { navigate(`/projects/${project.id}`); setDoc("problem") }}>{t("ide.problems")}</TreeButton>
                          <TreeButton onClick={() => { navigate(`/projects/${project.id}`); setDoc("model") }}>{t("ide.models")}</TreeButton>
                          <TreeButton onClick={() => { navigate(`/projects/${project.id}`); setDoc("equations") }}>{t("studio.equations")}</TreeButton>
                          <TreeButton onClick={() => { navigate(`/projects/${project.id}`); setDoc("data") }}>{t("ide.data")}</TreeButton>
                          <TreeButton onClick={() => { navigate(`/projects/${project.id}`); setDoc("results"); setBottomTab("agents"); setBottomOpen(true) }}>{t("ide.runs")}</TreeButton>
                          <TreeButton onClick={() => { navigate(`/projects/${project.id}`); setDoc("results") }}>{t("ide.reports")}</TreeButton>
                          <TreeButton onClick={() => { navigate(`/projects/${project.id}`); setDoc("lifecycle"); setLifeSection("overview") }}>{t("lifecycle.nav.overview")}</TreeButton>
                          <TreeButton onClick={() => { navigate(`/projects/${project.id}`); setDoc("lifecycle"); setLifeSection("requirements") }}>{t("lifecycle.nav.requirements")}</TreeButton>
                          <TreeButton onClick={() => { navigate(`/projects/${project.id}`); setDoc("lifecycle"); setLifeSection("data") }}>{t("lifecycle.nav.data")}</TreeButton>
                          <TreeButton onClick={() => { navigate(`/projects/${project.id}`); setDoc("lifecycle"); setLifeSection("models") }}>{t("lifecycle.nav.models")}</TreeButton>
                          <TreeButton onClick={() => { navigate(`/projects/${project.id}`); setDoc("lifecycle"); setLifeSection("runs") }}>{t("lifecycle.nav.runs")}</TreeButton>
                          <TreeButton onClick={() => { navigate(`/projects/${project.id}`); setDoc("lifecycle"); setLifeSection("analyses") }}>{t("lifecycle.nav.analyses")}</TreeButton>
                          <TreeButton onClick={() => { navigate(`/projects/${project.id}`); setDoc("lifecycle"); setLifeSection("decisions") }}>{t("lifecycle.nav.decisions")}</TreeButton>
                          <TreeButton onClick={() => { navigate(`/projects/${project.id}`); setDoc("lifecycle"); setLifeSection("artifacts") }}>{t("lifecycle.nav.artifacts")}</TreeButton>
                          <TreeButton onClick={() => { navigate(`/projects/${project.id}`); setDoc("lifecycle"); setLifeSection("activity") }}>{t("lifecycle.nav.activity")}</TreeButton>
                        </div>
                      ) : null}
                    </div>
                  )
                })}
              </div>
            ) : (
              <div className="min-h-0 flex-1 overflow-auto">
                {templates.map((item) => (
                  <button key={item.id} type="button" className="block w-full px-2 py-1 text-left hover:bg-sidebar-accent" onClick={() => void createFromTemplate(item)}>
                    <div className="truncate">{zh ? item.title_zh : item.title_en}</div>
                    <div className="truncate text-[11px] text-sidebar-foreground/60">{item.category}</div>
                  </button>
                ))}
              </div>
            )}
          </aside>
        ) : null}
        {leftOpen && !narrow ? <Splitter onReset={() => setLeftWidth(248)} onMouseDown={(event) => dragWidth(event, leftWidth, setLeftWidth, 180, 460, leftPanelRef.current)} /> : null}

        <div
          className="relative flex min-w-0 flex-1 flex-col"
          onDragEnter={(event) => {
            if ([...event.dataTransfer.types].includes("Files")) setDropping(true)
          }}
          onDragOver={(event) => {
            if ([...event.dataTransfer.types].includes("Files")) {
              event.preventDefault()
              setDropping(true)
            }
          }}
          onDragLeave={() => setDropping(false)}
          onDrop={(event) => {
            setDropping(false)
            const file = event.dataTransfer.files?.[0]
            if (!file) return
            event.preventDefault()
            const name = file.name.toLowerCase()
            if ((name.endsWith(".txt") || name.endsWith(".md")) && doc === "problem") {
              void file.text().then((text) => setStatement(text))
              return
            }
            openTable(file)
          }}
        >
          {dropping ? <div className="pointer-events-none absolute inset-1 z-20 border border-dashed border-primary bg-primary/5 px-3 py-2 text-xs">{t("ux.dropHint")}</div> : null}
          {projectId ? (
            <Tabs value={doc} onValueChange={(value) => { setDoc(value as DocId); if (value === "lifecycle") setLifeSection("board") }} className="app-docs flex min-h-0 flex-1 flex-col gap-0">
              <TabsList className="w-full justify-start rounded-none border-b">
                <TabsTrigger value="problem">{t("studio.problem")}{dirty ? <span className="app-unsaved" data-unsaved="problem" /> : null}</TabsTrigger>
                <TabsTrigger value="model">{t("studio.model")}{dirty ? <span className="app-unsaved" /> : null}</TabsTrigger>
                <TabsTrigger value="data">{t("ide.data")}</TabsTrigger>
                <TabsTrigger value="equations">{t("studio.equations")}</TabsTrigger>
                <TabsTrigger value="results">{t("studio.results")}</TabsTrigger>
                <TabsTrigger value="analysis">{t("ide.analysis")}</TabsTrigger>
                <TabsTrigger value="export">{t("studio.export")}</TabsTrigger>
                <TabsTrigger value="lifecycle">{t("lifecycle.tab")}</TabsTrigger>
              </TabsList>
              {celebrate && run?.status === "completed" ? (
                <div className="app-banner" data-banner="success">
                  <span>{t("ide.solvedBanner")}</span>
                  <Button size="xs" className="ml-auto" onClick={() => setCelebrate(false)}>{t("ide.tourDone")}</Button>
                </div>
              ) : null}
              {run?.pending_gate ? (
                <div className="app-banner" data-banner="approval">
                  <span>{t("studio.waiting")}</span>
                  <span className="text-muted-foreground">{t(`gates.${run.pending_gate.gate}`, { defaultValue: run.pending_gate.gate })}</span>
                  <Button size="xs" className="ml-auto" onClick={() => void decide("approved")}>{t("ide.approve")}</Button>
                  <Button size="xs" variant="outline" onClick={() => setDoc(run.pending_gate?.gate === "equations" ? "equations" : run.pending_gate?.gate === "model" ? "model" : "problem")}>{t("ide.editGate")}</Button>
                  <Button size="xs" variant="outline" onClick={() => void decide("rejected")}>{t("ide.reject")}</Button>
                </div>
              ) : null}
              {advice ? (
                <div className="app-banner" data-recommend>
                  <span>{zh ? advice.reason_zh : advice.reason_en}</span>
                  {solver === advice.solver ? <span className="text-muted-foreground">{t("ux.recommendMatch")}</span> : (
                    <Button size="xs" className="ml-auto" onClick={() => { setSolver(advice.solver); if (advice.algorithm) setAlgorithm(advice.algorithm) }}>{t("ux.recommendAdopt")}</Button>
                  )}
                </div>
              ) : null}
              <div className="min-h-0 flex-1 overflow-auto">
                {loadError ? <p className="p-3 text-destructive">{loadError}</p> : null}
                {doc === "problem" ? (
                  <div className="flex h-full flex-col">
                    <Input data-native-undo="" className="h-8 rounded-none border-0 border-b text-[13px]" value={title} onChange={(event) => setTitle(event.target.value)} />
                    <Textarea data-native-undo="" className="min-h-0 flex-1 resize-none rounded-none border-0 font-mono text-[13px]" value={statement} onChange={(event) => setStatement(event.target.value)} />
                    {questions.length ? (
                      <div className="border-t px-2 py-1 text-xs">
                        <div className="font-medium">{t("studio.questions")}</div>
                        {questions.map((item) => <div key={item}>{item}</div>)}
                      </div>
                    ) : null}
                  </div>
                ) : null}
                {doc === "model" ? (
                  <div className="h-full min-h-[280px]">
                    <AmlEditor editorRef={editorRef} value={dsl} onChange={onEditorChange} diagnostics={diagnostics} minimap={minimap} zh={zh} onCursor={(line, column) => setCursor({ line, column })} />
                  </div>
                ) : null}
                {doc === "data" ? <Suspense fallback={null}><ParameterGrid dsl={dsl} onCommit={commitDsl} /></Suspense> : null}
                {doc === "equations" ? (
                  <Suspense fallback={null}>
                    <StandardEquations
                      form={equations?.ok ? equations : equations && !equations.ok ? equations : run?.result?.standard_form || equations}
                      state={!dsl.trim() && run?.result?.standard_form?.ok ? "ready" : equationState}
                      zh={zh}
                      focus={equationFocus}
                    />
                  </Suspense>
                ) : null}
                {doc === "analysis" ? (
                  <Suspense fallback={null}>
                    <AnalysisBoard dsl={dsl} solver={solver} projectId={projectId} focus={analysisFocus} seed={analysisSeed} proposals={analysisProposals} />
                  </Suspense>
                ) : null}
                {doc === "results" ? (
                  <div className="space-y-2 p-2">
                    {run ? <Suspense fallback={null}><ResultsPanel run={run} history={runs} onOpenRun={setRun} onJumpConstraint={jumpConstraint} /></Suspense> : (
                      <div className="border border-dashed px-4 py-8 text-center">
                        <p className="text-sm">{t("results.empty")}</p>
                        <p className="mt-1 text-xs text-muted-foreground">{solveReason || t("ide.demoHint")}</p>
                      </div>
                    )}
                    <Suspense fallback={null}><WhatIfPanel dsl={dsl} solver={solver} /></Suspense>
                  </div>
                ) : null}
                {doc === "lifecycle" ? (
                  <Suspense fallback={null}>
                    <LifecycleBoard
                      projectId={projectId ? Number(projectId) : null}
                      section={lifeSection}
                      onSection={setLifeSection}
                      dsl={dsl}
                      onOpenProject={(id) => { navigate(`/projects/${id}`); setDoc("lifecycle"); setLifeSection("overview") }}
                    />
                  </Suspense>
                ) : null}
                {doc === "export" ? (
                  <div className="flex h-full flex-col">
                    <div className="flex gap-1 border-b p-1">
                      <Select value={target} onValueChange={setTarget}>
                        <SelectTrigger className="h-7 w-36 text-xs"><SelectValue /></SelectTrigger>
                        <SelectContent>
                          {targets.map((item) => (
                            <SelectItem key={item} value={item}>{item}</SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                      <Button size="sm" variant="outline" disabled={exporting} onClick={() => void exportModel()}>{exporting ? t("ide.exporting") : t("studio.export")}</Button>
                      {exporting ? (
                        <div className="h-1 w-28 self-center overflow-hidden bg-muted" role="progressbar" aria-valuetext={t("ide.exporting")} data-export-progress>
                          <div className="h-full w-1/2 bg-primary" />
                        </div>
                      ) : null}
                    </div>
                    <pre className="min-h-0 flex-1 overflow-auto p-3 font-mono text-[12px]">{exportCode || run?.result?.translations?.[target]?.code || ""}</pre>
                  </div>
                ) : null}
              </div>
            </Tabs>
          ) : doc === "lifecycle" ? (
            <Suspense fallback={null}>
              <LifecycleBoard projectId={null} section={lifeSection} onSection={setLifeSection} dsl={dsl} onOpenProject={(id) => { navigate(`/projects/${id}`); setDoc("lifecycle"); setLifeSection("overview") }} />
            </Suspense>
          ) : (
            <div data-screen="welcome" className="app-welcome min-h-0 flex-1 overflow-auto">
              <img src="/favicon.svg" alt="" className="mb-3 size-12" />
              <h1 className="text-base font-medium">{t("ide.welcomeTitle")}</h1>
              <p className="mt-1 max-w-xl text-[12px] text-muted-foreground">{t("ide.welcome")}</p>
              <p className="mt-1 max-w-xl text-[12px] text-muted-foreground">{t("ide.demoHint")}</p>
              {tourOn ? (
                <div className="app-tour" data-tour="start">
                  <div className="text-[11px] text-muted-foreground">{tourStep + 1}/3 · {t("ide.tourTitle")}</div>
                  <p className="mt-1 text-[13px]">{[t("ide.tour1"), t("ide.tour2"), t("ide.tour3")][tourStep]}</p>
                  <div className="mt-2 flex gap-2">
                    <Button size="sm" onClick={() => tourStep === 2 ? dismissTour() : setTourStep((step) => step + 1)}>{tourStep === 2 ? t("ide.tourDone") : t("ide.tourNext")}</Button>
                    <Button size="sm" variant="outline" onClick={dismissTour}>{t("ide.tourSkip")}</Button>
                  </div>
                </div>
              ) : null}
              <div className="mt-3 flex gap-2">
                <Button size="sm" onClick={() => setNewOpen(true)}>{t("ide.new")}</Button>
                <Button size="sm" variant="outline" onClick={() => { setDoc("lifecycle"); setLifeSection("board") }}>{t("lifecycle.open")}</Button>
                <Button size="sm" variant="outline" aria-label="Open library" onClick={() => { setLeftOpen(true); setSide("templates") }}>{t("nav.templates")}</Button>
              </div>
              <div className="mb-2 mt-5 text-xs font-medium text-muted-foreground">{t("ide.recent")}</div>
              <div className="max-w-xl border">
                {projects === null ? <div className="app-skeleton" /> : null}
                {(projects || []).map((project) => (
                  <button key={project.id} type="button" className="flex w-full items-center justify-between border-b px-2 py-1 text-left last:border-b-0 hover:bg-muted" onClick={() => navigate(`/projects/${project.id}`)}>
                    <span className="truncate">{project.title}</span>
                    <Badge variant="secondary">{t(`status.${project.status}`, { defaultValue: project.status })}</Badge>
                  </button>
                ))}
                {projects !== null && projects.length === 0 ? <div className="px-2 py-3 text-xs text-muted-foreground">{t("ide.emptyExplorer")}</div> : null}
              </div>
              <div className="mb-2 mt-4 text-xs font-medium text-muted-foreground">{t("templates.title")}</div>
              <div className="max-w-xl border">
                {templates.slice(0, 6).map((item) => (
                  <div key={item.id} className="flex items-center justify-between gap-2 border-b px-2 py-1 text-xs last:border-b-0">
                    <button type="button" className="min-w-0 flex-1 truncate text-left hover:underline" title={zh ? item.title_zh : item.title_en} onClick={() => void createFromTemplate(item)}>{zh ? item.title_zh : item.title_en}</button>
                    <span className="text-muted-foreground">{item.category}</span>
                    <button type="button" className="text-primary" aria-label="Solve sample" onClick={() => void solveTemplate(item)}>{t("ide.trySolve")}</button>
                  </div>
                ))}
              </div>
            </div>
          )}

          {bottomOpen ? (
            <>
              <Splitter horizontal onReset={() => setBottomHeight(168)} onMouseDown={dragHeight} />
              <section ref={bottomPanelRef} data-panel="bottom" className="shrink-0 border-t" style={{ height: bottomHeight }}>
                <Tabs value={bottomTab} onValueChange={(value) => setBottomTab(value as BottomTab)} className="flex h-full flex-col gap-0">
                  <TabsList className="h-7 w-full justify-start rounded-none bg-muted/40 px-1">
                    <TabsTrigger value="agents" className="h-6 rounded-none text-[11px]">{t("ide.log")}</TabsTrigger>
                    <TabsTrigger value="solver" className="h-6 rounded-none text-[11px]">{t("ide.solverOut")}</TabsTrigger>
                    <TabsTrigger value="diagnostics" className="h-6 rounded-none text-[11px]">{t("ide.diagnostics")}</TabsTrigger>
                    <TabsTrigger value="console" className="h-6 rounded-none text-[11px]">{t("ide.console")}</TabsTrigger>
                  </TabsList>
                  <div className="min-h-0 flex-1 overflow-auto p-2">
                    {bottomTab === "agents" ? (events.length ? <Timeline events={events} onRetry={() => void solve()} onStop={() => void stop()} /> : <p className="text-xs text-muted-foreground">{t("studio.emptyRun")}</p>) : null}
                    {bottomTab === "solver" ? (
                      solverEvents.length ? <Timeline events={solverEvents} /> : <p className="text-xs text-muted-foreground">{t("ide.noRun")}</p>
                    ) : null}
                    {bottomTab === "diagnostics" ? (
                      <div className="space-y-1 text-xs" data-panel="problems">
                        {diagnostics.length === 0 ? <p className="text-muted-foreground">{t("ide.problemsEmpty")}</p> : null}
                        {diagnostics.map((item, index) => {
                          const label = diagnosticLabel(item, zh)
                          return (
                            <button key={`${item.code || item.message}-${index}`} type="button" className="block w-full px-1 py-0.5 text-left hover:bg-muted" onClick={() => jumpDiagnostic(item.line)}>
                              <span className={item.level === "warning" ? "text-amber-700 dark:text-amber-300" : "text-destructive"}>{item.level}</span>
                              <span className="ml-2 font-mono">Ln {label.line}</span>
                              <span className="ml-2">{label.text}</span>
                            </button>
                          )
                        })}
                        {run?.status === "failed" && run.error ? <p className="text-destructive">{zh ? run.error : run.error_en || run.error}</p> : null}
                        {(run?.result?.diagnosis?.conflicts || []).map((item) => (
                          <button key={item.constraint} type="button" className="block w-full px-1 py-0.5 text-left hover:bg-muted" data-diagnosis={item.constraint} onClick={() => jumpConstraint(item.constraint)}>
                            <span className="text-destructive">{item.label}</span>
                            <span className="ml-2">{zh ? item.suggestion : item.suggestion_en}</span>
                          </button>
                        ))}
                        {run?.result?.verification ? <p>{zh ? run.result.verification.message : run.result.verification.message_en}</p> : null}
                      </div>
                    ) : null}
                    {bottomTab === "console" ? (
                      <pre className="font-mono text-[11px]">{consoleLines.join("\n") || t("ide.ready")}</pre>
                    ) : null}
                  </div>
                </Tabs>
              </section>
            </>
          ) : null}
        </div>

        {rightOpen && !narrow ? <Splitter onReset={() => setRightWidth(280)} onMouseDown={(event) => dragWidth(event, rightWidth, setRightWidth, 220, 460, rightPanelRef.current, true)} /> : null}
        {rightOpen ? (
          <aside ref={rightPanelRef} data-panel={rightTab} className={narrow ? "app-float right-0 flex w-72 flex-col border-l bg-sidebar text-sidebar-foreground" : "flex shrink-0 flex-col border-l bg-sidebar text-sidebar-foreground"} style={narrow ? undefined : { width: rightWidth }}>
            <div className="flex h-7 items-center gap-1 border-b border-sidebar-border px-1">
              <button type="button" className={rightTab === "inspector" ? "rounded bg-sidebar-accent px-2 py-0.5 text-[11px]" : "px-2 py-0.5 text-[11px] text-sidebar-foreground/70"} onClick={() => setRightTab("inspector")}>{t("ide.inspector")}</button>
              <button type="button" className={rightTab === "chat" ? "rounded bg-sidebar-accent px-2 py-0.5 text-[11px]" : "px-2 py-0.5 text-[11px] text-sidebar-foreground/70"} onClick={() => setRightTab("chat")}>{t("ide.chat")}</button>
              <button type="button" className="ml-auto px-1" aria-label={t("ide.close")} onClick={() => setRightOpen(false)}><X className="size-3" /></button>
            </div>
            {rightTab === "inspector" ? (
              <div className="min-h-0 flex-1 space-y-2 overflow-auto p-2 text-[12px]">
                <Label className="text-[11px] text-sidebar-foreground/70">{t("projects.name")}</Label>
                <Input data-native-undo="" className="h-7 border-sidebar-border bg-background text-foreground" value={title} onChange={(event) => setTitle(event.target.value)} />
                <div className="flex items-center justify-between">
                  <span>{t("studio.auto")}</span>
                  <Switch checked={auto} onCheckedChange={setAuto} />
                </div>
                <div className="text-sidebar-foreground/70">{t("results.objective")}</div>
                <div className="font-medium">{run?.objective || "—"}</div>
                <div className="text-sidebar-foreground/70">{t("studio.solver")}</div>
                <div>{run?.solver || solver}</div>
                {run ? <Badge variant="secondary">{t(`status.${run.status}`, { defaultValue: run.status })}</Badge> : null}
                <div className="flex items-center justify-between">
                  <span>{t("ux.notifyDone")}</span>
                  <Switch checked={notifyOn} aria-label={t("ux.notifyDone")} onCheckedChange={(value) => { setNotifyOn(value); localStorage.setItem("axiom.notify", value ? "1" : "0") }} />
                </div>
                <div className="flex items-center justify-between">
                  <span>{t("ux.sound")}</span>
                  <Switch checked={soundOn} aria-label={t("ux.sound")} onCheckedChange={(value) => { setSoundOn(value); localStorage.setItem("axiom.sound", value ? "1" : "0") }} />
                </div>
                <VersionHistory versions={versions} onSave={() => void saveVersion()} onRollback={rollback} />
              </div>
            ) : (
              <div className="flex min-h-0 flex-1 flex-col">
                <div className="flex min-h-0 flex-1 flex-col gap-2 overflow-auto p-2 text-[12px]">
                  {chat.length === 0 ? (
                    <div className="m-auto max-w-[16rem] text-center text-sidebar-foreground/70">
                      <p>{t("ide.chatEmpty")}</p>
                      <button type="button" className="mt-2 text-primary" onClick={() => setChatDraft(zh ? "这个结果里，哪个约束是紧的？" : "Which constraint is binding?")}>{zh ? "问一个约束" : "Ask about a constraint"}</button>
                    </div>
                  ) : null}
                  {chat.map((item, index) => (
                    <div key={`${item.role}-${index}`} className={item.role === "user" ? "app-bubble app-bubble-user" : "app-bubble"}>
                      <div className="mb-0.5 text-[10px] text-muted-foreground">{item.role === "user" ? user?.display_name : t("product")}</div>
                      {item.content}
                    </div>
                  ))}
                  {chatPending ? <div className="app-skeleton w-24" /> : null}
                </div>
                <form className="flex gap-1 border-t border-sidebar-border p-1" onSubmit={(event) => { event.preventDefault(); void sendChat() }}>
                  <Input data-native-undo="" className="h-7 border-sidebar-border bg-background text-foreground" value={chatDraft} placeholder={t("ide.chatPlaceholder")} onChange={(event) => setChatDraft(event.target.value)} />
                  <Button size="sm" type="submit" disabled={chatPending}>{t("ide.chatSend")}</Button>
                  <Button size="sm" type="button" variant="outline" disabled={chatPending} onClick={() => void makeProblem()}>{t("lifecycle.fromChat")}</Button>
                </form>
              </div>
            )}
          </aside>
        ) : null}
      </div>

      <footer className="app-status flex shrink-0 items-center gap-3 px-2">
        <span className="app-status-accent" />
        <span>{solver}</span>
        <span>{llm?.provider === "mock" || !llm ? t("ide.offline") : llm.provider}</span>
        <span>{run ? t(`status.${run.status}`, { defaultValue: run.status }) : t("ide.ready")}</span>
        {running ? <span data-solve-progress>{t("ux.progress", { percent: progressPercent(events.filter((item) => item.status === "done").length, events.length) })}</span> : null}
        {solveReason ? <span data-solve-reason>{solveReason}</span> : null}
        <span>{t("ide.agents")} {events.filter((item) => item.status === "running" || item.status === "waiting").length || (running ? 1 : 0)}</span>
        <span className="ml-auto" data-status-lang>{zh ? "中文" : "EN"}</span>
        <button type="button" onClick={() => void switchLocale(zh ? "en" : "zh-CN")}>{zh ? "Switch to English" : "中文"}</button>
        <span>{zh ? `行 ${cursor.line}，列 ${cursor.column}` : `Ln ${cursor.line}, Col ${cursor.column}`}</span>
      </footer>

      <input ref={importRef} className="hidden" type="file" accept=".lp,.mps,.txt,.aml,.axiom" onChange={(event) => { const file = event.target.files?.[0]; event.target.value = ""; if (file) void doImport(file) }} />
      <input ref={mathRef} className="hidden" type="file" accept=".qps,.nl,.osil,.xml,.cbf,.sdpa,.dat-s,.fzn,.mzn,.py,.mod,.gms,.zpl,.jl,.opl" onChange={(event) => { const file = event.target.files?.[0]; event.target.value = ""; if (file) void doImport(file) }} />
      <input ref={dataRef} className="hidden" type="file" accept=".csv,.xlsx,.xlsm" onChange={(event) => { const file = event.target.files?.[0]; event.target.value = ""; if (file) openTable(file) }} />

      {menu ? (
        <div role="menu" className="fixed z-50 min-w-36 border bg-popover py-1 text-xs shadow" style={{ left: menu.x, top: menu.y }}>
          <button type="button" role="menuitem" className="block w-full px-2 py-1 text-left hover:bg-muted" onClick={() => navigate(`/projects/${menu.id}`)}>{t("ide.open")}</button>
          <button type="button" role="menuitem" className="block w-full px-2 py-1 text-left hover:bg-muted" onClick={() => void copyText((projects || []).find((item) => item.id === menu.id)?.title || "")}>{t("ide.copyName")}</button>
          <button type="button" role="menuitem" className="block w-full px-2 py-1 text-left hover:bg-muted" onClick={() => void removeProject(menu.id)}>{t("ide.delete")}</button>
        </div>
      ) : null}

      <Dialog open={!ready ? false : !user} onOpenChange={() => undefined}>
        <DialogContent className="sm:max-w-sm" showCloseButton={false} onPointerDownOutside={(event) => event.preventDefault()} onEscapeKeyDown={(event) => event.preventDefault()}>
          <img src="/favicon.svg" alt="" className="mx-auto size-14" />
          <DialogHeader>
            <DialogTitle>{t("ide.signIn")}</DialogTitle>
          </DialogHeader>
          <p className="text-xs text-muted-foreground">{t("ide.signInLead")}</p>
          <SignInForm onDone={() => navigate("/")} />
        </DialogContent>
      </Dialog>

      <Dialog open={newOpen} onOpenChange={setNewOpen}>
        <DialogContent>
          <form onSubmit={createProject} className="space-y-3">
            <DialogHeader><DialogTitle>{t("ide.new")}</DialogTitle></DialogHeader>
            <Label className="text-xs">{t("projects.name")}</Label>
            <Input className="h-8" value={newTitle} onChange={(event) => setNewTitle(event.target.value)} required />
            <Label className="text-xs">{t("projects.statement")}</Label>
            <Textarea value={newStatement} onChange={(event) => setNewStatement(event.target.value)} rows={6} />
            <Button type="submit" size="sm">{t("projects.create")}</Button>
          </form>
        </DialogContent>
      </Dialog>

      <Dialog open={routeDialog === "settings"} onOpenChange={(open) => { if (!open) navigate(rememberedProject.current ? `/projects/${rememberedProject.current}` : "/") }}>
        <DialogContent className="max-h-[85vh] overflow-auto sm:max-w-6xl">
          <Suspense fallback={null}><SettingsPage /></Suspense>
        </DialogContent>
      </Dialog>
      <Dialog open={routeDialog === "workspaces"} onOpenChange={(open) => { if (!open) navigate(rememberedProject.current ? `/projects/${rememberedProject.current}` : "/") }}>
        <DialogContent className="max-h-[85vh] overflow-auto sm:max-w-3xl">
          <Suspense fallback={null}><WorkspacesPage /></Suspense>
        </DialogContent>
      </Dialog>
      <Dialog open={routeDialog === "audit"} onOpenChange={(open) => { if (!open) navigate(rememberedProject.current ? `/projects/${rememberedProject.current}` : "/") }}>
        <DialogContent className="max-h-[85vh] overflow-auto sm:max-w-4xl">
          <Suspense fallback={null}><AuditPage /></Suspense>
        </DialogContent>
      </Dialog>
      <Dialog open={routeDialog === "templates"} onOpenChange={(open) => { if (!open) navigate(rememberedProject.current ? `/projects/${rememberedProject.current}` : "/") }}>
        <DialogContent className="max-h-[85vh] overflow-auto sm:max-w-lg">
          <DialogHeader><DialogTitle>{t("templates.title")}</DialogTitle></DialogHeader>
          <div className="max-h-96 overflow-auto border">
            {templates.map((item) => (
              <button key={item.id} type="button" className="flex w-full items-center justify-between border-b px-2 py-1.5 text-left text-xs last:border-b-0 hover:bg-muted" onClick={() => void createFromTemplate(item)}>
                <span>{zh ? item.title_zh : item.title_en}</span>
                <span className="text-muted-foreground">{item.category}</span>
              </button>
            ))}
          </div>
        </DialogContent>
      </Dialog>
      <Dialog open={restore !== null} onOpenChange={(open) => { if (!open) { clearDraft(); setRestore(null) } }}>
        <DialogContent data-restore>
          <DialogHeader><DialogTitle>{t("ux.restoreTitle")}</DialogTitle></DialogHeader>
          <p className="text-xs text-muted-foreground">{t("ux.restoreLead")}</p>
          <div className="flex justify-end gap-2">
            <Button size="sm" variant="outline" onClick={() => { clearDraft(); setRestore(null) }}>{t("ux.discard")}</Button>
            <Button size="sm" onClick={() => {
              if (!restore) return
              setTitle(restore.title)
              setStatement(restore.statement)
              commitDsl(restore.dsl)
              setAuto(restore.auto)
              setSolver(restore.solver)
              if (restore.algorithm) setAlgorithm(restore.algorithm)
              setRestore(null)
            }}>{t("ux.restore")}</Button>
          </div>
        </DialogContent>
      </Dialog>
      <ImportWizard open={wizardFile !== null} file={wizardFile} dsl={dsl} onOpenChange={(open) => { if (!open) setWizardFile(null) }} onApply={(aml) => { commitDsl(aml); setDoc("data") }} />
      <IndustryGallery open={galleryOpen} templates={templates} onOpenChange={setGalleryOpen} onTry={(item) => void solveTemplate(item)} />
      <Suspense fallback={null}>
        <CompatibilityDialog open={compatOpen} onOpenChange={setCompatOpen} />
      </Suspense>
      <Dialog open={aboutOpen} onOpenChange={setAboutOpen}>
        <DialogContent className="sm:max-w-sm">
          <div className="flex items-start gap-3">
            <img src="/favicon.svg" alt="" className="size-12 shrink-0" />
            <div className="min-w-0">
              <DialogHeader><DialogTitle>{t("ide.about")}</DialogTitle></DialogHeader>
              <p className="mt-2 text-xs text-muted-foreground">{t("ide.aboutBody")}</p>
            </div>
          </div>
        </DialogContent>
      </Dialog>

      <Dialog open={gotoOpen} onOpenChange={setGotoOpen}>
        <DialogContent className="sm:max-w-xs">
          <form onSubmit={(event) => { event.preventDefault(); setGotoOpen(false); setDoc("model"); window.setTimeout(() => revealLine(editorRef.current?.view, Number(gotoLine)), 0) }}>
            <DialogHeader><DialogTitle>{t("ide.goto")}</DialogTitle></DialogHeader>
            <Input className="mt-2 h-8" value={gotoLine} onChange={(event) => setGotoLine(event.target.value)} inputMode="numeric" autoFocus />
            <Button className="mt-3 h-8" type="submit" size="sm">{t("ide.goto")}</Button>
          </form>
        </DialogContent>
      </Dialog>

      <Dialog open={shortcutsOpen} onOpenChange={setShortcutsOpen}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader><DialogTitle>{t("ide.shortcuts")}</DialogTitle></DialogHeader>
          <dl className="grid grid-cols-[8rem_1fr] gap-y-1 text-xs">
            {[
              ["Ctrl+Shift+P", t("ide.palette")],
              ["Ctrl+/", t("ide.shortcuts")],
              ["Ctrl+S", t("ide.save")],
              ["Ctrl+N", t("ide.new")],
              ["F5", t("ide.run")],
              ["Ctrl+F", t("ide.find")],
              ["Ctrl+G", t("ide.goto")],
              ["Ctrl+B", t("ide.explorer")],
              ["Ctrl+J", t("ide.bottom")],
              ["Ctrl+Alt+C", t("ux.copyConclusion")],
            ].map(([key, label]) => (
              <div key={key} className="contents">
                <dt className="font-mono text-muted-foreground">{key}</dt>
                <dd>{label}</dd>
              </div>
            ))}
          </dl>
        </DialogContent>
      </Dialog>

      <CommandDialog open={paletteOpen} onOpenChange={setPaletteOpen} title={t("ide.palette")}>
        <CommandInput placeholder={t("ide.palette")} />
        <CommandList>
          <CommandEmpty>{t("templates.empty")}</CommandEmpty>
          <CommandGroup heading={t("ide.palette")}>
            {commands.map((item) => (
              <CommandItem key={item.label} onSelect={() => { setPaletteOpen(false); item.run() }}>
                {item.label}
                {item.shortcut ? <CommandShortcut>{item.shortcut}</CommandShortcut> : null}
              </CommandItem>
            ))}
          </CommandGroup>
        </CommandList>
      </CommandDialog>
    </div>
  )
}

function Menu({ label, children }: { label: string; children: ReactNode }) {
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <button type="button" className="app-menu">{label}</button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="start" className="min-w-52">
        {children}
      </DropdownMenuContent>
    </DropdownMenu>
  )
}

function ToolButton({ label, children, pressed, labeled, primary, ...props }: ComponentProps<"button"> & { label: string; pressed?: boolean; labeled?: boolean; primary?: boolean }) {
  return (
    <button type="button" aria-label={label} aria-pressed={pressed} title={label} className={`app-tool${labeled ? " app-tool-labeled" : ""}${pressed ? " is-pressed" : ""}${primary ? " app-tool-primary" : ""}`} {...props}>
      {children}
      {labeled ? <span>{label}</span> : null}
    </button>
  )
}

function TreeButton({ children, onClick }: { children: string; onClick: () => void }) {
  return (
    <button type="button" className="block w-full rounded px-1 py-0.5 text-left text-sidebar-foreground/80 hover:bg-sidebar-accent" onClick={onClick}>
      {children}
    </button>
  )
}

function Splitter({ onMouseDown, onReset, horizontal = false }: { onMouseDown: (event: ReactMouseEvent) => void; onReset?: () => void; horizontal?: boolean }) {
  return (
    <div
      role="separator"
      aria-orientation={horizontal ? "horizontal" : "vertical"}
      data-orientation={horizontal ? "horizontal" : "vertical"}
      onMouseDown={onMouseDown}
      onDoubleClick={onReset}
      className="app-splitter"
    />
  )
}
