import { useEffect, useMemo, useState } from "react"
import { useTranslation } from "react-i18next"
import { ApiError, api } from "@/lib/api"
import { Button } from "@/components/ui/button"
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import type { AnalysisJob, CompatibilityCell, CompatibilityReport } from "@/components/analysis/types"

const TONE: Record<string, string> = {
  ok: "#2f6b4f",
  capable: "#8a7355",
  unsupported: "#b7b1a6",
  not_installed: "#d9d3c7",
  error: "#8c3a32",
  mismatch: "#8c3a32",
}

export function CompatibilityDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (open: boolean) => void }) {
  const { t, i18n } = useTranslation()
  const zh = i18n.language.startsWith("zh")
  const [report, setReport] = useState<CompatibilityReport | null>(null)
  const [error, setError] = useState("")
  const [job, setJob] = useState<AnalysisJob | null>(null)
  const [picked, setPicked] = useState<CompatibilityCell | null>(null)

  useEffect(() => {
    if (!open) return
    setError("")
    api.compatibility(false).then(setReport).catch((reason) => setError(reason instanceof ApiError ? (zh ? reason.message : reason.messageEn) : t("common.error")))
  }, [open, zh, t])

  useEffect(() => {
    if (!job || job.status !== "running") return
    const timer = window.setInterval(() => {
      api.analysisJob(job.id).then((next) => {
        setJob(next)
        const result = next.result as (CompatibilityReport & { kind?: string }) | null
        if (next.status !== "running" && result?.solvers) setReport(result)
        if (next.status === "failed") setError(zh ? next.error : next.error_en)
      }).catch(() => undefined)
    }, 800)
    return () => window.clearInterval(timer)
  }, [job, zh])

  const running = job?.status === "running"

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[85vh] overflow-hidden sm:max-w-6xl">
        <DialogHeader>
          <DialogTitle>{t("analysis.compatibility")}</DialogTitle>
        </DialogHeader>
        <p className="text-xs text-muted-foreground">{t("analysis.compatLead")}</p>
        <div className="flex flex-wrap items-center gap-2">
          <Button size="sm" variant="outline" disabled={running} onClick={() => api.compatibility(false).then(setReport)}>{t("analysis.structural")}</Button>
          <Button
            size="sm"
            disabled={running}
            onClick={() => {
              setError("")
              void api.startAnalysis({ kind: "compatibility", options: { execute: true } }).then(setJob).catch((reason) => setError(reason instanceof ApiError ? (zh ? reason.message : reason.messageEn) : t("common.error")))
            }}
          >
            {t("analysis.execute")}
          </Button>
          {running && job ? <span className="text-xs" data-analysis-progress={Math.round((job.progress || 0) * 100)}>{Math.round((job.progress || 0) * 100)}%</span> : null}
          <Button size="xs" variant="ghost" disabled={!running || !job} onClick={() => job && void api.cancelAnalysis(job.id).then(setJob)}>{t("analysis.cancel")}</Button>
        </div>
        {error ? <p className="text-xs text-destructive">{error}</p> : null}
        {report ? (
          <div className="min-h-0 space-y-3 overflow-auto pr-1" data-compatibility-matrix>
            <p className="text-xs">{Object.entries(report.summary).map(([key, value]) => `${key} ${value}`).join(" · ")}</p>
            <Matrix title={t("analysis.solverAxis")} classes={report.classes} cells={report.solvers} zh={zh} onPick={setPicked} />
            <Matrix title={t("analysis.languageAxis")} classes={report.classes} cells={report.languages} zh={zh} onPick={setPicked} />
            {picked ? (
              <p className="border px-2 py-1 text-xs" data-compatibility-reason>
                <span className="font-medium">{picked.name} · {picked.class} · {picked.status}. </span>
                {zh ? picked.reason : picked.reason_en}
              </p>
            ) : null}
          </div>
        ) : null}
      </DialogContent>
    </Dialog>
  )
}

function Matrix({ title, classes, cells, zh, onPick }: { title: string; classes: string[]; cells: CompatibilityCell[]; zh: boolean; onPick: (cell: CompatibilityCell) => void }) {
  const names = useMemo(() => unique(cells.map((cell) => cell.name)), [cells])
  const lookup = useMemo(() => {
    const map = new Map<string, CompatibilityCell>()
    for (const cell of cells) map.set(`${cell.name}|${cell.class}`, cell)
    return map
  }, [cells])
  return (
    <section>
      <h3 className="mb-1 text-sm font-medium">{title}</h3>
      <div className="overflow-auto">
        <table className="border-collapse text-[11px]">
          <thead>
            <tr>
              <th className="sticky left-0 bg-background px-1 py-1 text-left">{title}</th>
              {classes.map((kind) => <th key={kind} className="px-1 py-1 font-normal">{kind}</th>)}
            </tr>
          </thead>
          <tbody>
            {names.map((name) => (
              <tr key={name}>
                <th className="sticky left-0 bg-background px-1 py-0.5 text-left font-normal">{name}</th>
                {classes.map((kind) => {
                  const cell = lookup.get(`${name}|${kind}`)
                  if (!cell) return <td key={kind} />
                  return (
                    <td key={kind} className="p-0.5">
                      <button
                        type="button"
                        data-compatibility-status={cell.status}
                        title={zh ? cell.reason : cell.reason_en}
                        className="block min-w-8 px-1 py-0.5 text-white"
                        style={{ background: TONE[cell.status] || "#5e584f" }}
                        onClick={() => onPick(cell)}
                      >
                        {cell.status === "ok" ? "ok" : cell.status === "capable" ? "·" : cell.status === "unsupported" ? "—" : cell.status === "not_installed" ? "∅" : "!"}
                      </button>
                    </td>
                  )
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  )
}

function unique(values: string[]) {
  const seen: string[] = []
  for (const value of values) if (!seen.includes(value)) seen.push(value)
  return seen
}
