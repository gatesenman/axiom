import { useEffect, useState } from "react"
import { useTranslation } from "react-i18next"
import { Windowed } from "@/components/windowed"
import { stepGap } from "@/lib/decision"
import type { RunEvent } from "@/lib/types"

export function Timeline({ events, onRetry, onStop }: { events: RunEvent[]; onRetry?: () => void; onStop?: () => void }) {
  const { i18n } = useTranslation()
  const zh = i18n.language.startsWith("zh")
  const [open, setOpen] = useState<number | null>(null)
  const [now, setNow] = useState(() => Date.now())
  const live = events.some((event) => event.status === "running" || event.status === "waiting")

  useEffect(() => {
    if (!live) return
    const timer = window.setInterval(() => setNow(Date.now()), 1000)
    return () => window.clearInterval(timer)
  }, [live])

  if (!events.length) return null
  const done = events.filter((event, index) => event.status === "done" || (event.status === "running" && events[index + 1])).length
  return (
    <div className="space-y-0" data-timeline="agents">
      <div className="px-1 pb-2 text-[11px] text-muted-foreground">
        <div className="mb-1 h-1 bg-muted" data-solve-progress={done}>
          <div className="h-full bg-primary" style={{ width: `${events.length ? Math.round((100 * done) / events.length) : 0}%` }} />
        </div>
        {done}/{events.length}
      </div>
      {events.length > 48 && open === null ? (
        <Windowed count={events.length} rowHeight={28} height={240}>
          {(index) => <TimelineRow events={events} index={index} zh={zh} now={now} open={open} setOpen={setOpen} onRetry={onRetry} onStop={onStop} />}
        </Windowed>
      ) : events.map((event, index) => (
        <TimelineRow key={event.id} events={events} index={index} zh={zh} now={now} open={open} setOpen={setOpen} onRetry={onRetry} onStop={onStop} event={event} />
      ))}
    </div>
  )
}

function TimelineRow({
  events,
  index,
  event,
  zh,
  now,
  open,
  setOpen,
  onRetry,
  onStop,
}: {
  events: RunEvent[]
  index: number
  event?: RunEvent
  zh: boolean
  now: number
  open: number | null
  setOpen: (value: number | null) => void
  onRetry?: () => void
  onStop?: () => void
}) {
  const { t } = useTranslation()
  const row = event || events[index]
  if (!row) return null
  const text = zh ? row.detail : row.detail_en || row.detail
  const title = zh ? row.title : row.title_en || row.title
  const later = events[index + 1]
  const status = row.status === "running" && later ? "done" : row.status
  const gap = status === "running"
    ? stepGap(new Date(now).toISOString(), row.created_at)
    : stepGap(row.created_at, events[index - 1]?.created_at)
  const expanded = open === row.id
  return (
    <div className="app-agent-card">
      <button type="button" className="flex w-full items-baseline gap-2 text-left" onClick={() => setOpen(expanded ? null : row.id)}>
        <span className={status === "running" || status === "waiting" ? "size-1.5 shrink-0 rounded-full bg-primary" : "size-1.5 shrink-0 rounded-full bg-muted-foreground/40"} />
        <span className="min-w-0 flex-1 truncate text-[13px]">{title}</span>
        {gap ? <span className="shrink-0 text-[11px] text-muted-foreground">{gap}</span> : null}
        <span className="shrink-0 text-[11px] text-muted-foreground">{t(`status.${status}`, { defaultValue: status })}</span>
      </button>
      {expanded ? (
        <div className="mt-1 pl-4 text-[12px] text-muted-foreground">
          <div className="mb-1 text-[11px]">{row.agent}</div>
          {text ? <p className="whitespace-pre-wrap">{text}</p> : null}
          <div className="mt-2 flex gap-2">
            {status === "error" && onRetry ? <button type="button" className="text-primary" onClick={onRetry}>{t("common.retry")}</button> : null}
            {(status === "running" || status === "waiting") && onStop ? <button type="button" className="text-primary" onClick={onStop}>{t("ide.stop")}</button> : null}
          </div>
        </div>
      ) : null}
    </div>
  )
}
