import { useEffect, useState } from "react"
import { Link, useParams } from "react-router-dom"
import { useTranslation } from "react-i18next"
import { ResultsPanel } from "@/components/results-panel"
import { Timeline } from "@/components/timeline"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { api } from "@/lib/api"
import type { Run, RunEvent } from "@/lib/types"

export function RunPage() {
  const { id = "" } = useParams()
  const { t } = useTranslation()
  const [run, setRun] = useState<Run | null>(null)
  const [events, setEvents] = useState<RunEvent[]>([])

  useEffect(() => {
    api.run(Number(id)).then(setRun).catch(() => setRun(null))
    api.events(Number(id)).then(setEvents).catch(() => setEvents([]))
  }, [id])

  if (!run) return <p className="text-sm text-muted-foreground">{t("common.loading")}</p>

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3">
        <h1 className="text-2xl font-semibold">#{run.id}</h1>
        <Badge>{t(`status.${run.status}`, { defaultValue: run.status })}</Badge>
        <Button variant="outline" size="sm" asChild>
          <Link to={`/projects/${run.project_id}`}>{t("dashboard.open")}</Link>
        </Button>
      </div>
      <Timeline events={events} />
      <ResultsPanel run={run} />
    </div>
  )
}
