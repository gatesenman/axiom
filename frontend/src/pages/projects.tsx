import { useEffect, useState, type FormEvent } from "react"
import { Link } from "react-router-dom"
import { useTranslation } from "react-i18next"
import { toast } from "sonner"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle, DialogTrigger } from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { Textarea } from "@/components/ui/textarea"
import { ApiError, api } from "@/lib/api"
import type { Project } from "@/lib/types"

export function ProjectsPage() {
  const { t, i18n } = useTranslation()
  const [rows, setRows] = useState<Project[] | null>(null)
  const [error, setError] = useState("")
  const [open, setOpen] = useState(false)
  const [title, setTitle] = useState("")
  const [statement, setStatement] = useState("")

  function load() {
    api.projects().then(setRows).catch((reason: unknown) => {
      setError(reason instanceof ApiError ? (i18n.language.startsWith("zh") ? reason.message : reason.messageEn) : t("common.error"))
    })
  }

  useEffect(() => {
    load()
  }, [])

  async function create(event: FormEvent) {
    event.preventDefault()
    try {
      await api.createProject({ title, statement, locale: i18n.language.startsWith("zh") ? "zh-CN" : "en" })
      setOpen(false)
      setTitle("")
      setStatement("")
      load()
    } catch (reason) {
      toast.error(reason instanceof ApiError ? reason.message : t("common.error"))
    }
  }

  async function remove(project: Project) {
    await api.deleteProject(project.id)
    load()
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between gap-3">
        <h1 className="text-2xl font-semibold">{t("projects.title")}</h1>
        <Dialog open={open} onOpenChange={setOpen}>
          <DialogTrigger asChild>
            <Button>{t("projects.new")}</Button>
          </DialogTrigger>
          <DialogContent>
            <form onSubmit={create} className="space-y-4">
              <DialogHeader>
                <DialogTitle>{t("projects.new")}</DialogTitle>
              </DialogHeader>
              <div className="space-y-2">
                <Label>{t("projects.name")}</Label>
                <Input value={title} onChange={(event) => setTitle(event.target.value)} required />
              </div>
              <div className="space-y-2">
                <Label>{t("projects.statement")}</Label>
                <Textarea value={statement} onChange={(event) => setStatement(event.target.value)} rows={6} />
              </div>
              <DialogFooter>
                <Button type="submit">{t("projects.create")}</Button>
              </DialogFooter>
            </form>
          </DialogContent>
        </Dialog>
      </div>
      {error ? <p className="text-sm text-destructive">{error}</p> : null}
      {!rows ? <p className="text-sm text-muted-foreground">{t("common.loading")}</p> : null}
      {rows && rows.length === 0 ? (
        <Card><CardContent className="py-10 text-sm text-muted-foreground">{t("projects.empty")}</CardContent></Card>
      ) : null}
      {rows && rows.length > 0 ? (
        <Card>
          <CardContent className="px-0">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>{t("projects.name")}</TableHead>
                  <TableHead>status</TableHead>
                  <TableHead>{t("projects.updated")}</TableHead>
                  <TableHead />
                </TableRow>
              </TableHeader>
              <TableBody>
                {rows.map((project) => (
                  <TableRow key={project.id}>
                    <TableCell>
                      <Link className="font-medium hover:underline" to={`/projects/${project.id}`}>{project.title}</Link>
                      <div className="line-clamp-1 max-w-xl text-xs text-muted-foreground">{project.statement}</div>
                    </TableCell>
                    <TableCell><Badge variant="secondary">{t(`status.${project.status}`, { defaultValue: project.status })}</Badge></TableCell>
                    <TableCell className="text-xs text-muted-foreground">{project.updated_at.slice(0, 16).replace("T", " ")}</TableCell>
                    <TableCell>
                      <Button variant="ghost" size="sm" onClick={() => void remove(project)}>{t("projects.delete")}</Button>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
      ) : null}
    </div>
  )
}
