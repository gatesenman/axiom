import { useEffect, useState } from "react"
import { Link } from "react-router-dom"
import { useTranslation } from "react-i18next"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { ApiError, api } from "@/lib/api"
import { useAuth } from "@/lib/auth"
import type { Dashboard } from "@/lib/types"

export function DashboardPage() {
  const { t, i18n } = useTranslation()
  const { user } = useAuth()
  const [data, setData] = useState<Dashboard | null>(null)
  const [error, setError] = useState("")

  function load() {
    setError("")
    api.dashboard().then(setData).catch((reason: unknown) => {
      setError(reason instanceof ApiError ? (i18n.language.startsWith("zh") ? reason.message : reason.messageEn) : t("common.error"))
    })
  }

  useEffect(() => {
    load()
  }, [])

  if (error) {
    return (
      <div className="space-y-3">
        <p className="text-sm text-destructive">{error}</p>
        <Button variant="outline" onClick={load}>{t("common.retry")}</Button>
      </div>
    )
  }
  if (!data) return <p className="text-sm text-muted-foreground">{t("common.loading")}</p>

  const stats = [
    [t("dashboard.projects"), data.projects],
    [t("dashboard.runs"), data.runs],
    [t("dashboard.completed"), data.completed],
    [t("dashboard.solvers"), data.solvers_available],
  ] as const

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">{t("dashboard.hello", { name: user?.display_name })}</h1>
          <p className="mt-1 max-w-2xl text-sm text-muted-foreground">{t("dashboard.lead")}</p>
        </div>
        <Button asChild>
          <Link to="/projects">{t("dashboard.new")}</Link>
        </Button>
      </div>
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        {stats.map(([label, value]) => (
          <Card key={label}>
            <CardHeader><CardTitle className="text-sm font-normal text-muted-foreground">{label}</CardTitle></CardHeader>
            <CardContent><div className="text-3xl font-semibold">{value}</div></CardContent>
          </Card>
        ))}
      </div>
      <div>
        <h2 className="mb-3 text-sm font-medium">{t("dashboard.recent")}</h2>
        {data.recent_projects.length === 0 ? (
          <Card>
            <CardContent className="py-8 text-sm text-muted-foreground">{t("dashboard.empty")}</CardContent>
          </Card>
        ) : (
          <div className="grid gap-3 md:grid-cols-2">
            {data.recent_projects.map((project) => (
              <Card key={project.id}>
                <CardHeader>
                  <CardTitle className="flex items-center justify-between gap-2">
                    <span className="truncate">{project.title}</span>
                    <Badge variant="secondary">{t(`status.${project.status}`, { defaultValue: project.status })}</Badge>
                  </CardTitle>
                </CardHeader>
                <CardContent className="space-y-3">
                  <p className="line-clamp-3 text-sm text-muted-foreground">{project.statement || project.dsl || "—"}</p>
                  <Button variant="outline" size="sm" asChild>
                    <Link to={`/projects/${project.id}`}>{t("dashboard.open")}</Link>
                  </Button>
                </CardContent>
              </Card>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
