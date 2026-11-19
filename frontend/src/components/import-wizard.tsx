import { useEffect, useState } from "react"
import { useTranslation } from "react-i18next"
import { toast } from "sonner"
import { Button } from "@/components/ui/button"
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { ApiError, api } from "@/lib/api"

type Mapping = { column: string; role: string; name: string; indexes: string[] }
type Preview = {
  encoding: string
  sheet: string | null
  sheets: string[]
  columns: string[]
  rows: string[][]
  row_count: number
  mapping: Mapping[]
}

export function ImportWizard({
  open,
  file,
  dsl,
  onOpenChange,
  onApply,
}: {
  open: boolean
  file: File | null
  dsl: string
  onOpenChange: (open: boolean) => void
  onApply: (aml: string) => void
}) {
  const { t, i18n } = useTranslation()
  const zh = i18n.language.startsWith("zh")
  const [preview, setPreview] = useState<Preview | null>(null)
  const [mapping, setMapping] = useState<Mapping[]>([])
  const [error, setError] = useState("")
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    if (!open || !file) return
    let alive = true
    setError("")
    setPreview(null)
    void file.arrayBuffer().then(async (buffer) => {
      const bytes = new Uint8Array(buffer)
      let binary = ""
      bytes.forEach((value) => {
        binary += String.fromCharCode(value)
      })
      try {
        const body = await api.previewTable({ filename: file.name, content_base64: btoa(binary) })
        if (!alive) return
        setPreview(body)
        setMapping(body.mapping)
      } catch (reason) {
        if (!alive) return
        setError(reason instanceof ApiError ? (zh ? reason.message : reason.messageEn) : t("common.error"))
      }
    })
    return () => {
      alive = false
    }
  }, [open, file, zh, t])

  async function apply() {
    if (!preview) return
    setBusy(true)
    try {
      const result = await api.applyTable({ dsl, columns: preview.columns, rows: preview.rows, mapping })
      onApply(result.aml)
      onOpenChange(false)
      toast.success(t("ux.applied"))
    } catch (reason) {
      setError(reason instanceof ApiError ? (zh ? reason.message : reason.messageEn) : t("common.error"))
    } finally {
      setBusy(false)
    }
  }

  const setColumns = mapping.filter((item) => item.role === "set").map((item) => item.column)

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-3xl">
        <DialogHeader>
          <DialogTitle>{t("ux.wizardTitle")}</DialogTitle>
        </DialogHeader>
        <div data-wizard="import" className="space-y-2 text-xs">
          {error ? <p className="text-destructive">{error}</p> : null}
          {!preview && !error ? <div className="app-skeleton" data-loading="import" /> : null}
          {preview ? (
            <>
              <p className="text-muted-foreground">
                {file?.name} · {preview.encoding}
                {preview.sheet ? ` · ${preview.sheet}` : ""} · {preview.row_count}
              </p>
              <div className="max-h-48 overflow-auto border">
                <table className="w-full">
                  <thead>
                    <tr>{preview.columns.map((column) => <th key={column} className="border-b px-1 py-1 text-left">{column}</th>)}</tr>
                  </thead>
                  <tbody>
                    {preview.rows.slice(0, 8).map((row, index) => (
                      <tr key={index}>{row.map((cell, cellIndex) => <td key={cellIndex} className="border-b px-1 py-0.5 font-mono">{cell}</td>)}</tr>
                    ))}
                  </tbody>
                </table>
              </div>
              {mapping.map((item, index) => (
                <div key={item.column} className="flex flex-wrap items-center gap-2">
                  <span className="w-28 truncate">{item.column}</span>
                  <Select
                    value={item.role}
                    onValueChange={(role) => setMapping((current) => current.map((row, rowIndex) => (rowIndex === index ? { ...row, role, indexes: role === "parameter" ? setColumns : [] } : row)))}
                  >
                    <SelectTrigger className="h-7 w-28" aria-label={item.column}><SelectValue /></SelectTrigger>
                    <SelectContent>
                      <SelectItem value="ignore">{t("ux.roleIgnore")}</SelectItem>
                      <SelectItem value="set">{t("ux.roleSet")}</SelectItem>
                      <SelectItem value="parameter">{t("ux.roleParam")}</SelectItem>
                    </SelectContent>
                  </Select>
                  <input
                    className="h-7 w-28 border px-1 font-mono"
                    value={item.name}
                    aria-label={`${item.column} name`}
                    onChange={(event) => setMapping((current) => current.map((row, rowIndex) => (rowIndex === index ? { ...row, name: event.target.value } : row)))}
                  />
                </div>
              ))}
              <Button size="sm" disabled={busy} onClick={() => void apply()}>{t("ux.applyData")}</Button>
            </>
          ) : null}
        </div>
      </DialogContent>
    </Dialog>
  )
}
