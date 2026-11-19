import { useEffect, useState } from "react"
import { useTranslation } from "react-i18next"
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts"
import { paper, paperTick } from "@/components/academic-figure"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Switch } from "@/components/ui/switch"
import { ApiError, api, formatNumber } from "@/lib/api"

type Knob = { id: string; target: string; name: string; index: string[]; label: string; value: number; min: number; max: number }
type Side = { status?: string; objective?: number | null; variables?: Record<string, number> }

export function WhatIfPanel({ dsl, solver }: { dsl: string; solver: string }) {
  const { t, i18n } = useTranslation()
  const zh = i18n.language.startsWith("zh")
  const [knobs, setKnobs] = useState<Knob[]>([])
  const [values, setValues] = useState<Record<string, number>>({})
  const [live, setLive] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState("")
  const [baseline, setBaseline] = useState<Side | null>(null)
  const [scenario, setScenario] = useState<Side | null>(null)

  useEffect(() => {
    if (!dsl.trim()) {
      setKnobs([])
      return
    }
    const timer = window.setTimeout(() => {
      api.whatIfKnobs(dsl).then((body) => {
        setKnobs(body.knobs)
        setValues(Object.fromEntries(body.knobs.map((knob) => [knob.id, knob.value])))
      }).catch(() => undefined)
    }, 400)
    return () => window.clearTimeout(timer)
  }, [dsl])

  async function solve(next = values) {
    const changes = knobs
      .filter((knob) => next[knob.id] !== undefined && Math.abs(next[knob.id] - knob.value) > 1e-8)
      .map((knob) => ({ target: knob.target, name: knob.name, index: knob.index, value: next[knob.id] }))
    setBusy(true)
    setError("")
    try {
      const report = await api.whatIf({ dsl, solver, changes })
      setBaseline(report.baseline)
      setScenario(report.scenario)
    } catch (reason) {
      setError(reason instanceof ApiError ? (zh ? reason.message : reason.messageEn) : t("common.error"))
    } finally {
      setBusy(false)
    }
  }

  useEffect(() => {
    if (!live || !dsl.trim()) return
    const timer = window.setTimeout(() => void solve(values), 600)
    return () => window.clearTimeout(timer)
  }, [live, values, dsl]) // eslint-disable-line react-hooks/exhaustive-deps

  if (!dsl.trim() || knobs.length === 0) return null
  const chart = baseline && scenario
    ? [
        { name: t("ux.baseline"), value: baseline.objective ?? 0 },
        { name: t("ux.scenario"), value: scenario.objective ?? 0 },
      ]
    : []

  return (
    <Card data-whatif>
      <CardHeader>
        <CardTitle>{t("ux.whatif")}</CardTitle>
      </CardHeader>
      <CardContent className="space-y-2 text-xs">
        <p className="text-muted-foreground">{t("ux.whatifLead")}</p>
        {knobs.slice(0, 6).map((knob) => (
          <label key={knob.id} className="grid grid-cols-[7rem_1fr_5rem] items-center gap-2">
            <span className="truncate font-mono">{knob.label}</span>
            <input
              type="range"
              min={knob.min}
              max={knob.max}
              step={Math.max(Math.abs(knob.value) / 100, 0.01)}
              value={values[knob.id] ?? knob.value}
              aria-label={knob.label}
              onChange={(event) => setValues((current) => ({ ...current, [knob.id]: Number(event.target.value) }))}
            />
            <input
              className="h-7 border px-1 font-mono"
              data-whatif-value={knob.name}
              value={String(values[knob.id] ?? knob.value)}
              onChange={(event) => setValues((current) => ({ ...current, [knob.id]: Number(event.target.value) }))}
            />
          </label>
        ))}
        <div className="flex items-center gap-2">
          <Button size="sm" variant="outline" disabled={busy} onClick={() => void solve()}>{busy ? t("ux.solving") : t("ux.resimulate")}</Button>
          <Switch checked={live} onCheckedChange={setLive} aria-label={t("ux.live")} />
          <span>{t("ux.live")}</span>
        </div>
        {error ? <p className="text-destructive">{error}</p> : null}
        {chart.length ? (
          <div className="fig-plot h-40" data-chart="whatif">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={chart}>
                <CartesianGrid stroke={paper.grid} strokeDasharray="0" />
                <XAxis dataKey="name" tick={paperTick} />
                <YAxis tick={paperTick} width={64} domain={[0, "auto"]} />
                <Tooltip />
                <Bar dataKey="value" fill={paper.bar} radius={0} isAnimationActive={false} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        ) : null}
        {baseline && scenario ? (
          <div className="grid grid-cols-2 gap-2">
            <div data-whatif-baseline>{t("ux.baseline")} {formatNumber(baseline.objective)}</div>
            <div data-whatif-scenario>{t("ux.scenario")} {formatNumber(scenario.objective)}</div>
          </div>
        ) : null}
      </CardContent>
    </Card>
  )
}
