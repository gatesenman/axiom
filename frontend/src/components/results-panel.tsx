import { useEffect, useMemo, useState, type ComponentProps } from "react"
import { useTranslation } from "react-i18next"
import { toast } from "sonner"
import { Bar, BarChart, Brush, CartesianGrid, ResponsiveContainer, Scatter, ScatterChart, Tooltip, XAxis, YAxis, ZAxis } from "recharts"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { AcademicFigure } from "@/components/academic-figure"
import { DistributionPlate, GanttPlate, Lollipop, NetworkPlate, ProfilePlate, SankeyPlate, ViolinPlate } from "@/components/figures/plates"
import { useFigurePalette } from "@/components/figures/theme"
import { FeasiblePlot } from "@/components/feasible-plot"
import { Windowed } from "@/components/windowed"
import { api, downloadPackage, downloadReport, formatNumber } from "@/lib/api"
import { compareSolutions } from "@/lib/compare"
import { ganttLayout, scenarioSeries, sensitivitySeries, variableBars } from "@/lib/charts"
import { figureNumbers, racePoints, scenarioCorrelation, slackHistogram, tornadoSeries } from "@/lib/figures"
import { divergingRdBu } from "@/lib/figure-theme"
import { copyText, executiveSummary, recommendation } from "@/lib/decision"
import type { FeasibleRegion, ParetoFront, ResultPayload, Run } from "@/lib/types"

function exact(value: unknown) {
  const number = Number(value)
  if (!Number.isFinite(number)) return "—"
  return new Intl.NumberFormat(undefined, { maximumFractionDigits: 8 }).format(number)
}

function ExactTip({ active, payload, label }: { active?: boolean; payload?: { value?: unknown; name?: string; payload?: { name?: string; constraint?: string } }[]; label?: string }) {
  if (!active || !payload?.length) return null
  const row = payload[0]?.payload
  const name = row?.constraint || row?.name || label || ""
  return (
    <div className="fig-tip">
      {name ? <div>{name}</div> : null}
      {payload.map((item, index) => (
        <div key={`${item.name || "v"}-${index}`}>{item.name ? `${item.name} ` : ""}{exact(item.value)}</div>
      ))}
    </div>
  )
}

function barName(state: unknown) {
  if (!state || typeof state !== "object") return ""
  const record = state as { name?: string; payload?: { name?: string } }
  return record.payload?.name || record.name || ""
}

export function ResultsPanel({ run, history = [], onOpenRun, onJumpConstraint }: { run: Run; history?: Run[]; onOpenRun?: (run: Run) => void; onJumpConstraint?: (name: string) => void }) {
  const { t, i18n } = useTranslation()
  const result = run.result || {}
  const zh = i18n.language.startsWith("zh")
  const palette = useFigurePalette()
  const tick = { fontSize: palette.axisSize, fill: palette.ink, fontFamily: palette.font }
  const variables = useMemo(() => variableBars(result.variables), [result.variables])
  const chartVariables = useMemo(() => variables.slice(0, 16), [variables])
  const sensitivity = useMemo(() => sensitivitySeries(result.sensitivity?.rows), [result.sensitivity])
  const scenarios = useMemo(() => scenarioSeries(result.scenarios), [result.scenarios])
  const gantt = useMemo(() => ganttLayout(result.views?.gantt), [result.views])
  const hasNumbers = variables.length > 0 || result.simulation || result.diagnosis
  const [selected, setSelected] = useState("")
  const [preview, setPreview] = useState(false)
  const [fetched, setFetched] = useState(result.figures || null)
  useEffect(() => {
    if (result.figures?.feasible_region || result.figures?.pareto) {
      setFetched(result.figures)
      return
    }
    const dsl = run.dsl || result.dsl || ""
    if (!dsl.trim()) return
    let alive = true
    api.figures(dsl).then((body) => { if (alive) setFetched(body) }).catch(() => undefined)
    return () => { alive = false }
  }, [run.dsl, result.dsl, result.figures])
  const tornado = useMemo(() => tornadoSeries(result.sensitivity?.rows), [result.sensitivity])
  const duals = useMemo(() => [
    ...Object.entries(result.duals || {})
      .filter(([, value]) => Math.abs(Number(value)) > 1e-8)
      .map(([name, value]) => ({ name, value: Number(value), constraint: name })),
    ...Object.entries(result.reduced_costs || {})
      .filter(([, value]) => Math.abs(Number(value)) > 1e-8)
      .map(([name, value]) => ({ name: `rc:${name}`, value: Number(value), constraint: name })),
  ], [result.duals, result.reduced_costs])
  const slack = useMemo(() => slackHistogram((result.constraints || []).map((row) => row.slack)), [result.constraints])
  const corr = useMemo(() => scenarioCorrelation(result.scenarios), [result.scenarios])
  const race = useMemo(() => racePoints(result.race), [result.race])
  const region = stampOptimum(fetched?.feasible_region || result.figures?.feasible_region, result.variables)
  const pareto: ParetoFront | null = result.figures?.pareto || fetched?.pareto || null
  const numbers = figureNumbers([
    chartVariables.length > 0,
    sensitivity.length > 0,
    scenarios.length > 0,
    tornado.length > 0,
    duals.length > 0,
    Boolean(region?.polygon?.length),
    slack.length > 0,
    Boolean(corr),
    race.length > 0,
    Boolean(pareto?.points?.length),
  ])
  const completed = history.filter((item) => item.status === "completed" && item.result)
  const advice = recommendation({
    solver: run.solver || result.solver,
    objective: result.objective ?? (run.objective ? Number(run.objective) : null),
    verification: result.verification ? (zh ? result.verification.message : result.verification.message_en) : "",
    top: variables.slice(0, 2),
  }, zh)
  const conclusion = executiveSummary({
    title: result.title || result.formulation?.title,
    solver: run.solver || result.solver,
    status: result.status || run.status,
    objective: result.objective ?? (run.objective ? Number(run.objective) : null),
    variables: result.variables,
    constraints: result.constraints,
  }, zh)
  const [tipOn, setTipOn] = useState(() => localStorage.getItem("axiom.tip.conclusion") !== "off")

  async function copy(value: string) {
    await copyText(value)
    toast.success(t("results.copied"))
  }

  if (!hasNumbers && run.status !== "completed") {
    return (
      <div className="border border-dashed px-4 py-8 text-center">
        <p className="text-sm">{t("results.empty")}</p>
        <p className="mt-1 text-xs text-muted-foreground">{t("ide.demoHint")}</p>
      </div>
    )
  }

  return (
    <div className="space-y-2">
      <section className="app-decision" data-decision>
        <div className="min-w-0">
          <div className="text-[11px] font-medium tracking-wide text-muted-foreground uppercase">{t("results.recommend")}</div>
          <div className="app-decision-value">{formatNumber(result.objective ?? run.objective)}</div>
          <p className="mt-1 max-w-2xl text-[13px]">{advice}</p>
          <p className="mt-1 max-w-2xl text-[13px]" data-conclusion>{conclusion}</p>
          {tipOn ? (
            <p className="mt-1 flex items-center gap-2 text-[11px] text-muted-foreground" data-tip="conclusion">
              <span>{t("ux.tipConclusion")}</span>
              <button type="button" className="text-primary" onClick={() => { localStorage.setItem("axiom.tip.conclusion", "off"); setTipOn(false) }}>{t("ux.tipDismiss")}</button>
            </p>
          ) : null}
          <p className="mt-1 text-[11px] text-muted-foreground">{run.solver || result.solver} · {t("results.selectHint")}</p>
        </div>
        <div className="flex flex-wrap gap-1">
          <Button size="sm" onClick={() => void copy(advice)}>{t("results.copy")}</Button>
          <Button size="sm" variant="outline" onClick={() => void copy(conclusion)}>{t("ux.copyConclusion")}</Button>
          <Button size="sm" variant="outline" onClick={() => setPreview(true)}>{t("results.preview")}</Button>
          <Button size="sm" variant="outline" onClick={() => void downloadReport(run.id, "pdf", i18n.language)}>{t("results.downloadPdf")}</Button>
          <Button size="sm" variant="outline" onClick={() => void downloadPackage(run.id, i18n.language)}>{t("ux.package")}</Button>
          <Button size="sm" variant="outline" onClick={() => void downloadReport(run.id, "xlsx", i18n.language)}>{t("results.downloadXlsx")}</Button>
        </div>
      </section>

      {completed.length > 1 ? (
        <Card>
          <CardHeader><CardTitle>{t("results.compare")}</CardTitle></CardHeader>
          <CardContent>
            <Table>
              <TableBody>
                {completed.slice(0, 6).map((item) => (
                  <TableRow key={item.id} data-selected={item.id === run.id ? "true" : undefined}>
                    <TableCell>#{item.id}</TableCell>
                    <TableCell>{item.solver}</TableCell>
                    <TableCell className="font-mono">{formatNumber(item.result?.objective ?? item.objective)}</TableCell>
                    <TableCell>
                      {item.id === run.id ? null : <button type="button" className="text-primary" onClick={() => onOpenRun?.(item)}>{t("ide.open")}</button>}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
      ) : null}

      {result.simulation ? <SimulationCard result={result} /> : null}
      {result.diagnosis?.message ? (
        <Card>
          <CardHeader><CardTitle>{t("results.diagnosis")}</CardTitle></CardHeader>
          <CardContent className="space-y-1 text-sm">
            <p>{zh ? result.diagnosis.message : result.diagnosis.message_en}</p>
            {(result.diagnosis.conflicts || []).map((item) => (
              <button key={item.constraint} type="button" className="block text-left text-primary" data-diagnosis={item.constraint} onClick={() => onJumpConstraint?.(item.constraint)}>
                {zh ? item.suggestion : item.suggestion_en}
              </button>
            ))}
          </CardContent>
        </Card>
      ) : null}

      {completed.length > 1 ? <RunDiff current={run} other={completed.find((item) => item.id !== run.id) || completed[0]} /> : null}

      {chartVariables.length ? (
        <AcademicFigure id="variables" index={numbers[0]} title={t("figures.variableTitle")} subtitle={t("figures.variableSub")} caption={t("figures.variableCaption")} plotClass="h-64">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={chartVariables}>
              <CartesianGrid stroke={palette.grid} strokeDasharray="0" />
              <XAxis dataKey="name" interval={0} tick={tick} />
              <YAxis tick={tick} tickFormatter={(value) => formatNumber(value)} width={56} domain={[0, "auto"]} />
              <Tooltip content={<ExactTip />} />
              <QuietBar dataKey="value" fill={palette.bar} radius={0} onClick={(state) => setSelected(barName(state))} />
            </BarChart>
          </ResponsiveContainer>
        </AcademicFigure>
      ) : null}

      <div className="grid gap-2 lg:grid-cols-2">
        {variables.length ? (
          <Card>
            <CardHeader><CardTitle>{t("results.variables")}</CardTitle></CardHeader>
            <CardContent>
              <Table data-chart="variable-table">
                <TableHeader>
                  <TableRow>
                    <TableHead>name</TableHead>
                    <TableHead>value</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {variables.length <= 40 ? variables.map((row) => (
                    <TableRow key={row.name} data-selected={selected === row.name ? "true" : undefined} data-variable-row={row.name} onClick={() => setSelected(row.name)}>
                      <TableCell className="font-mono text-xs">{row.name}</TableCell>
                      <TableCell>
                        <button type="button" className="font-mono" title={t("results.copy")} onClick={() => void copy(String(row.value))}>{formatNumber(row.value)}</button>
                      </TableCell>
                    </TableRow>
                  )) : null}
                </TableBody>
              </Table>
              {variables.length > 40 ? (
                <Windowed count={variables.length} rowHeight={28} height={280}>
                  {(index) => {
                    const row = variables[index]
                    if (!row) return null
                    return (
                      <button type="button" data-variable-row={row.name} className="flex h-7 w-full items-center justify-between px-2 font-mono text-xs" onClick={() => { setSelected(row.name); void copy(String(row.value)) }}>
                        <span>{row.name}</span>
                        <span>{formatNumber(row.value)}</span>
                      </button>
                    )
                  }}
                </Windowed>
              ) : null}
            </CardContent>
          </Card>
        ) : null}
        {result.constraints?.length ? (
          <Card>
            <CardHeader><CardTitle>{t("results.constraints")}</CardTitle></CardHeader>
            <CardContent>
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>name</TableHead>
                    <TableHead>slack</TableHead>
                    <TableHead />
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {result.constraints.length <= 40 ? result.constraints.map((row) => (
                    <TableRow key={row.name}>
                      <TableCell className="font-mono text-xs">{row.name}</TableCell>
                      <TableCell>{formatNumber(row.slack)}</TableCell>
                      <TableCell>
                        {row.violated ? <Badge variant="destructive">violated</Badge> : row.binding ? <Badge>binding</Badge> : null}
                      </TableCell>
                    </TableRow>
                  )) : null}
                </TableBody>
              </Table>
              {result.constraints.length > 40 ? (
                <Windowed count={result.constraints.length} rowHeight={28} height={280}>
                  {(index) => {
                    const row = result.constraints?.[index]
                    if (!row) return null
                    return (
                      <div className="flex h-7 items-center gap-3 px-2 font-mono text-xs">
                        <span className="min-w-0 flex-1 truncate">{row.name}</span>
                        <span>{formatNumber(row.slack)}</span>
                        {row.violated ? <Badge variant="destructive">violated</Badge> : row.binding ? <Badge>binding</Badge> : null}
                      </div>
                    )
                  }}
                </Windowed>
              ) : null}
            </CardContent>
          </Card>
        ) : null}
      </div>

      {result.race?.length ? (
        <Card>
          <CardHeader><CardTitle>{t("results.race")}</CardTitle></CardHeader>
          <CardContent>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>solver</TableHead>
                  <TableHead>status</TableHead>
                  <TableHead>objective</TableHead>
                  <TableHead>s</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {result.race.map((row) => (
                  <TableRow key={row.solver}>
                    <TableCell>{row.solver}</TableCell>
                    <TableCell>{t(`status.${row.status}`, { defaultValue: row.status })}</TableCell>
                    <TableCell>{formatNumber(row.objective)}</TableCell>
                    <TableCell>{formatNumber(row.runtime_sec)}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
      ) : null}

      <div className="grid gap-2 lg:grid-cols-2">
        {sensitivity.length ? (
          <AcademicFigure id="sensitivity" index={numbers[1]} title={t("figures.spanTitle")} subtitle={t("results.sensitivityHint")} caption={t("figures.spanCaption")} plotClass="h-56">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={sensitivity} layout="vertical" margin={{ left: 8, right: 16, top: 8, bottom: 8 }}>
                <CartesianGrid stroke={palette.grid} strokeDasharray="0" />
                <XAxis type="number" domain={[0, "auto"]} tick={tick} tickFormatter={(value) => formatNumber(value)} />
                <YAxis type="category" dataKey="name" width={120} interval={0} tick={tick} />
                <Tooltip content={<ExactTip />} />
                <QuietBar dataKey="span" fill={palette.alt} radius={0} />
              </BarChart>
            </ResponsiveContainer>
          </AcademicFigure>
        ) : null}
        {scenarios.length > 2 ? (
          <AcademicFigure id="scenario-shape" index={numbers[2]} title={zh ? "情景分布" : "Scenario distribution"} caption={zh ? "小提琴是核密度，箱线是四分位，中位线单独着色。" : "The violin is a kernel density. The box is the interquartile range, with the median drawn separately."} plotClass="h-56">
            <ViolinPlate palette={palette} values={scenarios.map((row) => Number(row.objective)).filter((value) => Number.isFinite(value))} />
          </AcademicFigure>
        ) : null}
        {scenarios.length ? (
          <AcademicFigure id="scenarios" index={numbers[2]} title={t("figures.scenarioTitle")} subtitle={t("figures.scenarioSub")} caption={t("figures.scenarioCaption")} plotClass="h-64">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={scenarios}>
                <CartesianGrid stroke={palette.grid} strokeDasharray="0" />
                <XAxis dataKey="name" interval={0} tick={tick} />
                <YAxis tick={tick} width={72} domain={[0, "auto"]} tickFormatter={(value) => formatNumber(value)} />
                <Tooltip content={<ExactTip />} />
                <QuietBar dataKey="objective" fill={palette.bar} radius={0} />
              </BarChart>
            </ResponsiveContainer>
          </AcademicFigure>
        ) : null}
      </div>

      {tornado.length ? (
        <AcademicFigure id="tornado" index={numbers[3]} title={t("figures.tornadoTitle")} subtitle={t("figures.tornadoSub")} caption={t("figures.tornadoCaption")} plotClass="h-64">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={tornado} layout="vertical" stackOffset="sign" margin={{ left: 8, right: 16, top: 8, bottom: 28 }}>
              <CartesianGrid stroke={palette.grid} strokeDasharray="0" />
              <XAxis type="number" tick={tick} tickFormatter={(value) => formatNumber(value)} />
              <YAxis type="category" dataKey="name" width={120} interval={0} tick={tick} />
              <Tooltip content={<ExactTip />} />
              <QuietBar dataKey="down" stackId="swing" fill={palette.neg} radius={0} />
              <QuietBar dataKey="up" stackId="swing" fill={palette.bar} radius={0} />
              <Brush dataKey="name" height={16} stroke={palette.line} fill={palette.bg} travellerWidth={8} />
            </BarChart>
          </ResponsiveContainer>
        </AcademicFigure>
      ) : null}

      {duals.length ? (
        <AcademicFigure id="duals" index={numbers[4]} title={t("figures.dualTitle")} subtitle={t("figures.dualSub")} caption={t("figures.dualCaption")} plotClass="h-56">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={duals} layout="vertical" margin={{ left: 8, right: 16, top: 8, bottom: 28 }}>
              <CartesianGrid stroke={palette.grid} strokeDasharray="0" />
              <XAxis type="number" tick={tick} tickFormatter={(value) => formatNumber(value)} />
              <YAxis type="category" dataKey="name" width={120} interval={0} tick={tick} />
              <Tooltip content={<ExactTip />} />
              <QuietBar dataKey="value" fill={palette.bar} radius={0} />
              <Brush dataKey="name" height={16} stroke={palette.line} fill={palette.bg} travellerWidth={8} />
            </BarChart>
          </ResponsiveContainer>
        </AcademicFigure>
      ) : null}

      {duals.length ? (
        <AcademicFigure id="lollipop" index={numbers[4]} title={zh ? "对偶棒棒糖图" : "Dual lollipops"} caption={zh ? "按绝对值排序。零线左侧为负对偶或负检验数。" : "Sorted by magnitude. Negative duals and reduced costs sit left of zero."} plotClass="h-56" rows={duals.map((row) => ({ name: row.name, value: row.value }))}>
          <Lollipop palette={palette} rows={duals.map((row) => ({ name: row.name, value: row.value }))} />
        </AcademicFigure>
      ) : null}

      {region?.polygon?.length ? (
        <AcademicFigure id="feasible" index={numbers[5]} title={t("figures.regionTitle")} subtitle={`${region.x} × ${region.y}`} caption={t("figures.regionCaption")} plotClass="h-80">
          <FeasiblePlot region={region} />
        </AcademicFigure>
      ) : null}

      {slack.length ? (
        <AcademicFigure id="slack" index={numbers[6]} title={t("figures.slackTitle")} subtitle={t("figures.slackSub")} caption={t("figures.slackCaption")} plotClass="h-56">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={slack}>
              <CartesianGrid stroke={palette.grid} strokeDasharray="0" />
              <XAxis dataKey="name" interval={0} tick={tick} />
              <YAxis allowDecimals={false} tick={tick} width={36} domain={[0, "auto"]} />
              <Tooltip content={<ExactTip />} />
              <QuietBar dataKey="count" fill={palette.alt} radius={0} />
            </BarChart>
          </ResponsiveContainer>
        </AcademicFigure>
      ) : null}

      {corr ? (
        <AcademicFigure id="correlation" index={numbers[7]} title={t("figures.corrTitle")} subtitle={t("figures.corrSub")} caption={t("figures.corrCaption")} plotClass="h-auto">
          <CorrelationHeat names={corr.names} matrix={corr.matrix} />
        </AcademicFigure>
      ) : null}

      {race.length ? (
        <AcademicFigure id="race" index={numbers[8]} title={t("figures.raceTitle")} subtitle={t("figures.raceSub")} caption={t("figures.raceCaption")} plotClass="h-64">
          <ResponsiveContainer width="100%" height="100%">
            <ScatterChart margin={{ left: 8, right: 16, top: 8, bottom: 8 }}>
              <CartesianGrid stroke={palette.grid} strokeDasharray="0" />
              <XAxis dataKey="time" name="t (s)" unit=" s" tick={tick} domain={spreadDomain()} tickFormatter={(value) => formatNumber(value)} />
              <YAxis dataKey="objective" name="z" tick={tick} width={72} domain={spreadDomain()} tickFormatter={(value) => formatNumber(value)} />
              <ZAxis range={[64, 64]} />
              <Tooltip content={<ExactTip />} />
              <Scatter data={race} fill={palette.bar} line={{ stroke: palette.line }} isAnimationActive={false} />
            </ScatterChart>
          </ResponsiveContainer>
        </AcademicFigure>
      ) : null}

      {result.race && result.race.length > 1 ? (
        <AcademicFigure id="profile" index={numbers[8]} title={zh ? "性能剖面" : "Performance profile"} caption={zh ? "Dolan–Moré 曲线。τ = 1 表示该求解器在这道题上最快。" : "Dolan–Moré curve. τ = 1 means the solver was fastest on that instance."} plotClass="h-64" rows={result.race.map((row) => ({ solver: row.solver, time: row.runtime_sec }))}>
          <ProfilePlate palette={palette} records={result.race.filter((row) => (row.runtime_sec || 0) > 0).map((row) => ({ solver: row.solver, problem: "instance", time: row.runtime_sec || 0 }))} />
        </AcademicFigure>
      ) : null}

      {pareto?.points?.length ? (
        <AcademicFigure id="pareto" index={numbers[9]} title={t("figures.paretoTitle")} subtitle={`${pareto.x} / ${pareto.y}`} caption={t("figures.paretoCaption")} plotClass="h-64">
          <ResponsiveContainer width="100%" height="100%">
            <ScatterChart margin={{ left: 8, right: 16, top: 8, bottom: 8 }}>
              <CartesianGrid stroke={palette.grid} strokeDasharray="0" />
              <XAxis dataKey="x" name={pareto.x} tick={tick} domain={spreadDomain()} tickFormatter={(value) => formatNumber(value)} />
              <YAxis dataKey="y" name={pareto.y} tick={tick} width={56} domain={spreadDomain()} tickFormatter={(value) => formatNumber(value)} />
              <Tooltip content={<ExactTip />} />
              <Scatter data={pareto.points} fill={palette.ink} line={{ stroke: palette.bar }} isAnimationActive={false} />
            </ScatterChart>
          </ResponsiveContainer>
        </AcademicFigure>
      ) : null}

      {result.monte_carlo?.samples ? (
        <AcademicFigure id="distribution" index={numbers[6]} title={zh ? "目标分布" : "Objective distribution"} caption={zh ? "直方图、核密度和经验分布。竖线是 p05、中位数和 p95。" : "Histogram, kernel density, and empirical CDF. Ticks mark p05, the median, and p95."} plotClass="h-64" rows={(result.monte_carlo.values || []).map((value) => ({ value }))}>
          <p className="mb-1 text-xs opacity-70">n={result.monte_carlo.samples} · mean {formatNumber(result.monte_carlo.mean)} · std {formatNumber(result.monte_carlo.std)}</p>
          <DistributionPlate palette={palette} unit="" values={result.monte_carlo.values?.length ? result.monte_carlo.values : [Number(result.monte_carlo.p05), Number(result.monte_carlo.mean), Number(result.monte_carlo.p95)].filter((value) => Number.isFinite(value))} />
        </AcademicFigure>
      ) : null}

      {gantt.length ? (
        <Card>
          <CardHeader><CardTitle>{t("results.gantt")}</CardTitle></CardHeader>
          <CardContent className="space-y-2" data-chart="gantt">
            {result.views?.gantt?.length ? <GanttPlate palette={palette} now={Math.max(...result.views.gantt.map((row) => row.end)) * 0.55} rows={result.views.gantt.map((row) => ({ id: row.id, start: row.start, end: row.end, lane: row.id }))} /> : null}
            {gantt.map((row) => (
              <div key={row.id} className="grid grid-cols-[4rem_1fr] items-center gap-2 text-xs">
                <div>{row.id}</div>
                <div className="relative h-4 rounded bg-muted">
                  <div className="absolute h-4 rounded bg-primary" data-gantt-bar={row.id} style={{ left: `${row.left}%`, width: `${row.width}%` }} />
                </div>
              </div>
            ))}
          </CardContent>
        </Card>
      ) : null}

      {result.views?.network?.edges?.length ? (
        <Card>
          <CardHeader><CardTitle>{t("results.network")}</CardTitle></CardHeader>
          <CardContent className="space-y-2 text-sm">
            <SankeyPlate palette={palette} edges={result.views.network.edges} />
            <NetworkPlate palette={palette} nodes={result.views.network.nodes} edges={result.views.network.edges} />
            {result.views.network.edges.map((edge) => (
              <div key={`${edge.source}-${edge.target}`} className="flex justify-between font-mono text-xs">
                <span>{edge.source} → {edge.target}</span>
                <span>{formatNumber(edge.value)}</span>
              </div>
            ))}
          </CardContent>
        </Card>
      ) : null}

      <Dialog open={preview} onOpenChange={setPreview}>
        <DialogContent className="app-print sm:max-w-lg">
          <DialogHeader><DialogTitle>{t("results.preview")}</DialogTitle></DialogHeader>
          <p className="text-sm">{advice}</p>
          <div className="mt-2 font-mono text-lg">{formatNumber(result.objective ?? run.objective)}</div>
          <ul className="mt-2 space-y-1 text-sm">
            {variables.slice(0, 8).map((row) => <li key={row.name}>{row.name} = {exact(row.value)}</li>)}
          </ul>
          <Button className="mt-3" size="sm" onClick={() => window.print()}>{t("results.print")}</Button>
        </DialogContent>
      </Dialog>
    </div>
  )
}

function RunDiff({ current, other }: { current: Run; other: Run }) {
  const { t } = useTranslation()
  const diff = compareSolutions(
    { objective: current.result?.objective ?? current.objective, variables: current.result?.variables },
    { objective: other.result?.objective ?? other.objective, variables: other.result?.variables },
  )
  return (
    <Card>
      <CardHeader><CardTitle>{t("ux.diff")}</CardTitle></CardHeader>
      <CardContent>
        <p className="mb-1 text-xs text-muted-foreground">#{other.id} → #{current.id}</p>
        <div data-run-diff className="text-sm">{t("results.objective")} {formatNumber(diff.objectiveDelta)}</div>
        <Table>
          <TableBody>
            {diff.rows.slice(0, 12).map((row) => (
              <TableRow key={row.name}>
                <TableCell className="font-mono text-xs">{row.name}</TableCell>
                <TableCell>{formatNumber(row.left)}</TableCell>
                <TableCell>{formatNumber(row.right)}</TableCell>
                <TableCell>{formatNumber(row.delta)}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </CardContent>
    </Card>
  )
}

function spreadDomain() {
  const pad = (end: "min" | "max") => (value: number) => {
    const span = Math.max(Math.abs(value) * 0.08, 1e-3)
    return end === "min" ? value - span : value + span
  }
  return [pad("min"), pad("max")] as const
}

function stampOptimum(region: FeasibleRegion | null | undefined, variables?: Record<string, number>) {
  if (!region?.polygon?.length) return null
  const x = Number(variables?.[region.x])
  const y = Number(variables?.[region.y])
  if (!Number.isFinite(x) || !Number.isFinite(y)) return region
  return { ...region, optimum: { x, y } }
}

function CorrelationHeat({ names, matrix }: { names: string[]; matrix: number[][] }) {
  const palette = useFigurePalette()
  const cell = 42
  const label = 88
  const size = label + names.length * cell + 8
  return (
    <svg viewBox={`0 0 ${size} ${size}`} className="h-auto max-h-80 w-full" role="img">
      {names.map((name, column) => (
        <text key={`x-${name}`} x={label + column * cell + cell / 2} y={label - 10} textAnchor="middle" fill={palette.ink} fontSize="12" fontFamily='"Liberation Serif", Georgia, serif'>{name}</text>
      ))}
      {matrix.map((row, i) => row.map((value, j) => (
        <g key={`${names[i]}-${names[j]}`}>
          <rect x={label + j * cell} y={label + i * cell} width={cell - 2} height={cell - 2} fill={heat(value)} stroke={palette.grid}>
            <title>{`${names[i]} × ${names[j]}: ${value.toFixed(4)}`}</title>
          </rect>
          <text x={label + j * cell + (cell - 2) / 2} y={label + i * cell + cell / 2 + 4} textAnchor="middle" fill={palette.ink} fontSize="11" fontFamily='"Liberation Serif", Georgia, serif'>{value.toFixed(2)}</text>
        </g>
      )))}
      {names.map((name, row) => (
        <text key={`y-${name}`} x={label - 8} y={label + row * cell + cell / 2 + 4} textAnchor="end" fill={palette.ink} fontSize="12" fontFamily='"Liberation Serif", Georgia, serif'>{name}</text>
      ))}
    </svg>
  )
}

function heat(value: number) {
  return divergingRdBu(Math.max(-1, Math.min(1, value)))
}

function QuietBar(props: ComponentProps<typeof Bar>) {
  return <Bar isAnimationActive={false} animationDuration={0} {...props} />
}

function SimulationCard({ result }: { result: ResultPayload }) {
  const { t } = useTranslation()
  const sim = result.simulation
  if (!sim) return null
  return (
    <Card>
      <CardHeader><CardTitle>{t("results.simulation")}</CardTitle></CardHeader>
      <CardContent>
        <div className="mb-3 grid grid-cols-2 gap-3 text-sm md:grid-cols-4">
          <Stat label="served" value={sim.served} />
          <Stat label="wait" value={formatNumber(sim.avg_wait)} />
          <Stat label="sojourn" value={formatNumber(sim.avg_sojourn)} />
          <Stat label="util" value={formatNumber(sim.utilization)} />
        </div>
        <div className="h-48" data-chart="simulation">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={sim.timeline}>
              <XAxis dataKey="t" tick={{ fontSize: 11 }} />
              <YAxis tick={{ fontSize: 11 }} tickFormatter={(value) => formatNumber(value)} width={48} domain={[0, "auto"]} />
              <Tooltip content={<ExactTip />} />
              <QuietBar dataKey="wait" fill="var(--chart-4)" radius={3} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      </CardContent>
    </Card>
  )
}

function Stat({ label, value }: { label: string; value: string | number }) {
  return (
    <div>
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className="text-lg font-medium">{value}</div>
    </div>
  )
}
