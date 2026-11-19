import { useEffect, useId, useMemo, useRef, useState } from "react"
import { Bar, BarChart, Brush, CartesianGrid, Line, LineChart, ResponsiveContainer, Scatter, ScatterChart, Tooltip, XAxis, YAxis } from "recharts"
import { AcademicFigure } from "@/components/academic-figure"
import { ConvergencePlate, DistributionPlate, MorrisPlate, SobolPlate, TornadoPlate } from "@/components/figures/plates"
import { useFigurePalette } from "@/components/figures/theme"
import { colormap, divergingRdBu, OKABE_ITO } from "@/lib/figure-theme"
import { paretoMask } from "@/lib/figure-geometry"

export type StudyPoint = {
  id: string
  label?: string
  values?: Record<string, number | null>
  objectives?: Record<string, number | null>
  feasible?: boolean
  minimize?: number[]
}

type Common = {
  selected?: string | null
  compare?: string | null
  onSelect?: (id: string) => void
  units?: Record<string, string>
  rows?: Array<Record<string, string | number | null | undefined>>
}

export function ParetoChart({ points, index, zh, selected, compare, onSelect, units }: { points: StudyPoint[]; index: number; zh: boolean } & Common) {
  const palette = useFigurePalette()
  const tick = { fontSize: palette.axisSize, fill: palette.ink, fontFamily: palette.font }
  const data = points
    .filter((point) => point.minimize && point.minimize.length >= 2)
    .map((point) => ({ id: point.id, x: point.minimize![0], y: point.minimize![1], z: point.minimize![2] ?? 0, feasible: point.feasible }))
  const front = paretoMask(data, true)
  const rest = data.filter((point, index) => !front[index] && point.id !== selected && point.id !== compare)
  const hot = data.filter((point, index) => front[index] || point.id === selected || point.id === compare)
  const three = data.some((point) => point.z !== 0)
  const choose = (row: unknown) => {
    const id = pointId(row)
    if (id) onSelect?.(id)
  }
  return (
    <div className="grid gap-2 lg:grid-cols-2">
      <AcademicFigure id="pareto" index={index} title={zh ? "帕累托前沿" : "Pareto front"} caption={zh ? "坐标是最小化后的目标。点一个设计，其他图会跟着高亮。" : "Axes are the minimized objectives. Click a design to highlight it everywhere."} plotClass="h-64" rows={data.map((point) => ({ id: point.id, f1: point.x, f2: point.y, f3: point.z }))}>
        <ResponsiveContainer width="100%" height="100%">
          <ScatterChart>
            <CartesianGrid stroke={palette.grid} />
            <XAxis dataKey="x" type="number" tick={tick} name="f1" unit={units?.f1 || ""} />
            <YAxis dataKey="y" type="number" tick={tick} name="f2" unit={units?.f2 || ""} />
            <Tooltip content={<UnitTip units={units} />} />
            <Brush dataKey="x" height={16} stroke={palette.bar} />
            <Scatter data={rest} fill={palette.muted} fillOpacity={0.35} onClick={choose} />
            <Scatter data={hot} fill={palette.neg} onClick={choose} />
          </ScatterChart>
        </ResponsiveContainer>
      </AcademicFigure>
      {three ? <ProjectedCloud points={data} index={index + 1} zh={zh} selected={selected} onSelect={onSelect} /> : null}
    </div>
  )
}

export function ParallelChart({ points, index, zh, selected, onSelect, units }: { points: StudyPoint[]; index: number; zh: boolean } & Common) {
  const palette = useFigurePalette()
  const discovered = useMemo(() => keysOf(points), [points])
  const [order, setOrder] = useState<string[]>([])
  const keys = order.length === discovered.length && order.every((key) => discovered.includes(key)) ? order : discovered
  const [brush, setBrush] = useState<{ key: string; lo: number; hi: number } | null>(null)
  const drag = useRef<{ key: string; y0: number } | null>(null)
  const width = 640
  const height = 280
  const ranges = useMemo(() => keyRanges(points, keys), [points, keys])
  const visible = points.filter((point) => !brush || inBrush(point, brush))
  function yOf(key: string, value: number) {
    const range = ranges[key]
    const span = range.max - range.min || 1
    return 24 + (1 - (value - range.min) / span) * (height - 48)
  }
  return (
      <AcademicFigure id="parallel" index={index} title={zh ? "平行坐标" : "Parallel coordinates"} caption={zh ? "在坐标轴上拖出一段即可刷选。点击轴名把它移到最右侧。点一条线会在其他图里高亮。" : "Drag an axis to brush. Click an axis name to move it to the right. Click a line to highlight it everywhere."} plotClass="h-72" rows={visible.map((point) => ({ id: point.id, ...point.values, ...point.objectives }))}>
      <svg
        viewBox={`0 0 ${width} ${height}`}
        className="h-full w-full"
        onMouseMove={(event) => {
          if (!drag.current) return
          const svg = event.currentTarget
          const rect = svg.getBoundingClientRect()
          const y = ((event.clientY - rect.top) / rect.height) * height
          const key = drag.current.key
          const range = ranges[key]
          const toValue = (py: number) => range.max - ((py - 24) / (height - 48)) * (range.max - range.min || 1)
          const a = toValue(drag.current.y0)
          const b = toValue(y)
          setBrush({ key, lo: Math.min(a, b), hi: Math.max(a, b) })
        }}
        onMouseUp={() => { drag.current = null }}
        onMouseLeave={() => { drag.current = null }}
      >
        {keys.map((key, indexKey) => {
          const x = 40 + (indexKey * (width - 80)) / Math.max(1, keys.length - 1)
          return (
            <g key={key}>
              <line x1={x} x2={x} y1={24} y2={height - 24} stroke={palette.ink} strokeWidth={palette.weights.axis} />
              <text x={x} y={16} textAnchor="middle" fill={palette.ink} fontSize={11} fontFamily={palette.font} style={{ cursor: "pointer" }} onClick={() => setOrder(rotateKey(keys, indexKey))}>{key}</text>
              {brush?.key === key ? (
                <g>
                  <rect x={x - 7} y={Math.min(yOf(key, brush.lo), yOf(key, brush.hi))} width={14} height={Math.max(6, Math.abs(yOf(key, brush.hi) - yOf(key, brush.lo)))} fill={palette.bar} opacity={0.16} />
                  <rect x={x - 6} y={yOf(key, brush.hi) - 3} width={12} height={6} fill={palette.bar} />
                  <rect x={x - 6} y={yOf(key, brush.lo) - 3} width={12} height={6} fill={palette.bar} />
                </g>
              ) : null}
              <rect
                x={x - 8}
                y={24}
                width={16}
                height={height - 48}
                fill="transparent"
                onMouseDown={(event) => {
                  const rect = event.currentTarget.ownerSVGElement!.getBoundingClientRect()
                  drag.current = { key, y0: ((event.clientY - rect.top) / rect.height) * height }
                }}
              />
            </g>
          )
        })}
        {points.map((point) => {
          const faded = brush && !inBrush(point, brush)
          const active = point.id === selected
          const d = keys.map((key, indexKey) => {
            const x = 40 + (indexKey * (width - 80)) / Math.max(1, keys.length - 1)
            const value = numberOf(point, key)
            return `${indexKey === 0 ? "M" : "L"} ${x} ${yOf(key, value)}`
          }).join(" ")
          return (
            <path
              key={point.id}
              d={d}
              fill="none"
              stroke={active ? palette.neg : palette.categorical[indexHue(point.id) % palette.categorical.length]}
              strokeWidth={active ? palette.weights.emphasis : palette.weights.data}
              opacity={faded ? 0.08 : active ? 1 : 0.28}
              onClick={() => onSelect?.(point.id)}
            >
              <title>{tooltipText(point, keys, units)}</title>
            </path>
          )
        })}
      </svg>
    </AcademicFigure>
  )
}

export function MatrixChart({ points, index, zh, selected, compare, onSelect, units }: { points: StudyPoint[]; index: number; zh: boolean } & Common) {
  const palette = useFigurePalette()
  const keys = keysOf(points).slice(0, 4)
  return (
    <AcademicFigure id="splom" index={index} title={zh ? "散点图矩阵" : "Scatter-plot matrix"} caption={zh ? "同一设计点在各投影里用同一颜色标出。" : "The same design point keeps its color in every panel."} plotClass="h-72">
      <div className="grid h-full gap-1" style={{ gridTemplateColumns: `repeat(${keys.length}, minmax(0, 1fr))` }}>
        {keys.flatMap((yKey) => keys.map((xKey) => (
          <svg key={`${xKey}-${yKey}`} viewBox="0 0 80 80" className="h-full w-full" style={{ background: palette.bg }}>
            {points.map((point) => {
              const rangeX = keyRanges(points, [xKey])[xKey]
              const rangeY = keyRanges(points, [yKey])[yKey]
              const x = 6 + ((numberOf(point, xKey) - rangeX.min) / (rangeX.max - rangeX.min || 1)) * 68
              const y = 74 - ((numberOf(point, yKey) - rangeY.min) / (rangeY.max - rangeY.min || 1)) * 68
              const marked = point.id === selected || point.id === compare
              return <circle key={point.id} cx={x} cy={y} r={marked ? 3.2 : 1.8} fill={marked ? palette.neg : palette.bar} onClick={() => onSelect?.(point.id)}><title>{tooltipText(point, [xKey, yKey], units)}</title></circle>
            })}
          </svg>
        )))}
      </div>
    </AcademicFigure>
  )
}

export function SurfaceChart({ surface, index, zh }: { surface: { x: number[]; y: number[]; z: number[][]; xlabel: string; ylabel: string; zlabel: string }; index: number; zh: boolean }) {
  const palette = useFigurePalette()
  const flat = surface.z.flat()
  const low = Math.min(...flat)
  const high = Math.max(...flat)
  const rows = surface.z.map((row, j) => ({ y: surface.y[j], ...Object.fromEntries(row.map((value, i) => [`x${i}`, value])) }))
  return (
    <div className="grid gap-2 lg:grid-cols-2">
      <AcademicFigure id="contour" index={index} title={zh ? "响应面等高线" : "Response-surface contours"} caption={`${surface.xlabel} × ${surface.ylabel}`} plotClass="h-64" rows={rows}>
        <svg viewBox="0 0 320 220" className="h-full w-full">
          {surface.z.map((row, j) => row.map((value, i) => {
            const t = (value - low) / (high - low || 1)
            const w = 280 / row.length
            const h = 180 / surface.z.length
            return <rect key={`${i}-${j}`} x={30 + i * w} y={10 + j * h} width={w + 0.4} height={h + 0.4} fill={mix(t)}><title>{`${surface.xlabel}=${surface.x[i].toFixed(3)}, ${surface.ylabel}=${surface.y[j].toFixed(3)}, ${surface.zlabel}=${value.toFixed(4)}`}</title></rect>
          }))}
          <text x="160" y="214" textAnchor="middle" fontSize="11" fill={palette.ink} fontFamily={palette.font}>{surface.xlabel}</text>
          <text x="12" y="100" fontSize="11" fill={palette.ink} fontFamily={palette.font} transform="rotate(-90 12 100)">{surface.ylabel}</text>
        </svg>
      </AcademicFigure>
      <AcademicFigure id="surface" index={index + 1} title={zh ? "响应面" : "Response surface"} caption={zh ? "斜投影，纵轴是代理模型的预测。" : "Oblique view. The vertical axis is the surrogate prediction."} plotClass="h-64">
        <SurfaceMesh surface={surface} zLabel={surface.zlabel} />
      </AcademicFigure>
    </div>
  )
}

export function SobolChart({ rows, index, zh }: { rows: Array<{ name: string; S1: number; ST: number; ci?: number }>; index: number; zh: boolean }) {
  const palette = useFigurePalette()
  return (
    <AcademicFigure id="sobol" index={index} title={zh ? "Sobol 指数" : "Sobol indices"} caption={zh ? "S1 是一阶指数，ST 是总效应。有置信区间时画出须线。" : "S1 is the first-order index and ST is the total effect. Whiskers appear when a confidence interval is reported."} plotClass="h-56" rows={rows.map((row) => ({ name: row.name, S1: row.S1, ST: row.ST, ci: row.ci }))}>
      <SobolPlate palette={palette} rows={rows.map((row) => ({ name: row.name, s1: row.S1, st: row.ST, ci: row.ci }))} />
    </AcademicFigure>
  )
}

export function MorrisChart({ rows, index, zh }: { rows: Array<{ name: string; mu_star: number; sigma: number }>; index: number; zh: boolean }) {
  const palette = useFigurePalette()
  return (
    <AcademicFigure id="morris" index={index} title={zh ? "Morris μ*–σ" : "Morris μ*–σ"} caption={zh ? "虚线是 μ* 与 σ 的中位数，四个象限区分线性、非线性与可忽略因子。" : "Dashed lines are the medians of μ* and σ. The quadrants separate linear, nonlinear, and negligible factors."} plotClass="h-56" rows={rows}>
      <MorrisPlate palette={palette} rows={rows.map((row) => ({ name: row.name, mu: row.mu_star, sigma: row.sigma }))} />
    </AcademicFigure>
  )
}

export function TornadoChart({ rows, index, zh }: { rows: Array<{ name: string; low: number | null; high: number | null; base: number }>; index: number; zh: boolean }) {
  const palette = useFigurePalette()
  const data = rows.map((row) => ({ name: row.name, down: (row.low ?? row.base) - row.base, up: (row.high ?? row.base) - row.base }))
  return (
    <AcademicFigure id="tornado-analysis" index={index} title={zh ? "目标系数允许范围" : "Objective-coefficient ranges"} caption={zh ? "零线是当前系数。左右伸出的是最优基保持不变的下界和上界。" : "The zero line is the current coefficient. Bars reach the bounds that keep the optimal basis."} plotClass="h-56" rows={rows.map((row) => ({ name: row.name, min: row.low, max: row.high, coefficient: row.base }))}>
      <TornadoPlate palette={palette} rows={data} />
    </AcademicFigure>
  )
}

export function HistoryChart({ rows, index, zh }: { rows: Array<{ objective?: number | null; violation?: number | null; residual?: number | null }>; index: number; zh: boolean }) {
  const palette = useFigurePalette()
  const data = rows.map((row, i) => ({ step: i + 1, objective: row.objective, violation: row.violation, residual: row.residual }))
  const finite = data.map((row) => Number(row.objective)).filter((value) => Number.isFinite(value))
  const best = finite.length ? Math.min(...finite.map((value) => Math.abs(value))) : 0
  return (
    <AcademicFigure id="convergence" index={index} title={zh ? "收敛历史" : "Convergence history"} caption={zh ? "纵轴是目标与当前最好值的对数间隙。圆点是刷新的 incumbent。" : "The vertical axis is the log gap to the best objective so far. Dots mark a new incumbent."} plotClass="h-56" rows={data}>
      <ConvergencePlate palette={palette} series={[{
        name: zh ? "间隙" : "gap",
        points: data.map((row) => ({ t: row.step, gap: Math.abs(Number(row.objective) - best) + 1e-6, lo: Number(row.residual) || undefined, hi: Number(row.violation) || undefined })),
      }]} />
    </AcademicFigure>
  )
}

export function DistributionChart({ values, histogram, index, zh }: { values: number[]; histogram?: { edges: number[]; counts: number[] }; index: number; zh: boolean }) {
  const palette = useFigurePalette()
  const tick = { fontSize: palette.axisSize, fill: palette.ink, fontFamily: palette.font }
  const bins = histogram?.counts.map((count, i) => ({ bin: histogram.edges[i]?.toFixed(2), count })) || []
  const ordered = [...values].sort((a, b) => a - b)
  const cdf = ordered.map((value, i) => ({ value, cdf: (i + 1) / ordered.length }))
  return (
    <div className="grid gap-2 lg:grid-cols-2">
      <AcademicFigure id="histogram" index={index} title={zh ? "目标分布" : "Objective distribution"} caption={zh ? "直方图、核密度和经验分布画在同一坐标系，刻度是 p05 / p50 / p95。" : "Histogram, kernel density, and the empirical distribution share one frame. Ticks mark p05, p50, and p95."} plotClass="h-52" rows={bins}>
        {values.length > 2 ? <DistributionPlate values={values} palette={palette} /> : (
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={bins}>
              <CartesianGrid stroke={palette.grid} vertical={false} />
              <XAxis dataKey="bin" tick={tick} />
              <YAxis tick={tick} />
              <Tooltip content={<UnitTip />} />
              <Bar dataKey="count" fill={palette.bar} />
            </BarChart>
          </ResponsiveContainer>
        )}
      </AcademicFigure>
      <AcademicFigure id="cdf" index={index + 1} title={zh ? "经验分布函数" : "Empirical distribution"} caption={zh ? "样本的累积分布。" : "Empirical cumulative distribution of the samples."} plotClass="h-52" rows={cdf}>
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={cdf}>
            <CartesianGrid stroke={palette.grid} />
            <XAxis dataKey="value" tick={tick} />
            <YAxis tick={tick} domain={[0, 1]} />
            <Tooltip content={<UnitTip />} />
            <Line dataKey="cdf" stroke={palette.bar} dot={false} strokeWidth={palette.weights.data} />
          </LineChart>
        </ResponsiveContainer>
      </AcademicFigure>
    </div>
  )
}

export function Heatmap({ correlation, index, zh }: { correlation: { labels: string[]; matrix: number[][] }; index: number; zh: boolean }) {
  const palette = useFigurePalette()
  const n = correlation.labels.length
  return (
    <AcademicFigure id="correlation" index={index} title={zh ? "相关热图" : "Correlation heatmap"} caption={zh ? "设计列与目标的 Pearson 相关。" : "Pearson correlation of the design columns and the objective."} plotClass="h-64" rows={correlation.matrix.map((row, i) => ({ name: correlation.labels[i], ...Object.fromEntries(row.map((value, j) => [correlation.labels[j], value])) }))}>
      <svg viewBox={`0 0 ${40 + n * 36} ${28 + n * 28}`} className="h-full w-full">
        {correlation.matrix.map((row, i) => row.map((value, j) => (
          <g key={`${i}-${j}`}>
            <rect x={36 + j * 36} y={8 + i * 28} width={34} height={26} fill={diverging(value)} />
            <text x={53 + j * 36} y={25 + i * 28} textAnchor="middle" fontSize="9" fill={Math.abs(value) > 0.55 ? "#f7f7f7" : palette.ink} fontFamily={palette.font}>{value.toFixed(2)}</text>
          </g>
        )))}
        {correlation.labels.map((label, i) => <text key={label} x="4" y={24 + i * 28} fontSize="10" fill={palette.ink} fontFamily={palette.font}>{label}</text>)}
      </svg>
    </AcademicFigure>
  )
}

export function N2Chart({ diagram, index, zh, onInspect }: { diagram: { labels: string[]; cells: Array<{ row: number; col: number; from: string; to: string; variables: string[]; kind: string }> }; index: number; zh: boolean; onInspect: (cell: { from: string; to: string; variables: string[] }) => void }) {
  const palette = useFigurePalette()
  const marker = useId().replace(/:/g, "")
  const n = diagram.labels.length
  const size = 64
  return (
    <AcademicFigure id="n2" index={index} title={zh ? "N2 耦合图" : "N2 coupling diagram"} caption={zh ? "对角线是学科，非对角线是耦合变量。箭头从供方指向需方。" : "The diagonal is a discipline. Off-diagonal marks are coupling variables. Arrows run from the supplier to the consumer."} plotClass="h-72">
      <svg viewBox={`0 0 ${48 + n * size} ${36 + n * size}`} className="h-full w-full">
        <defs>
          <marker id={marker} markerWidth="6" markerHeight="6" refX="5" refY="3" orient="auto">
            <path d="M0,0 L6,3 L0,6 Z" fill={palette.neg} />
          </marker>
        </defs>
        {diagram.labels.map((label, i) => (
          <text key={label} x={40 + i * size + size / 2} y={16} textAnchor="middle" fontSize="11" fill={palette.ink} fontFamily={palette.font}>{label}</text>
        ))}
        {Array.from({ length: n }, (_, row) => Array.from({ length: n }, (_, col) => {
          const cell = diagram.cells.find((item) => item.row === row && item.col === col)
          const on = Boolean(cell && cell.kind !== "empty")
          return (
            <g key={`${row}-${col}`} onClick={() => cell && onInspect(cell)}>
              <rect x={40 + col * size} y={24 + row * size} width={size - 4} height={size - 4} fill={row === col ? OKABE_ITO[row % OKABE_ITO.length] : on ? palette.region : palette.bg} stroke={palette.grid} />
              {on && row !== col ? <path d={`M ${48 + col * size} ${40 + row * size} l 18 -8`} stroke={palette.neg} strokeWidth={1.2} markerEnd={`url(#${marker})`} /> : null}
              <text x={40 + col * size + (size - 4) / 2} y={24 + row * size + 34} textAnchor="middle" fontSize="10" fill={palette.ink} fontFamily={palette.font}>
                {cell?.variables.slice(0, 2).join(", ")}
              </text>
              {cell ? <title>{`${cell.from} → ${cell.to}: ${cell.variables.join(", ")}`}</title> : null}
            </g>
          )
        }))}
      </svg>
    </AcademicFigure>
  )
}

export function ScheduleChart({ rows, index, zh, selected, onSelect }: { rows: Array<{ id: string; start: number; end: number; duration?: number }>; index: number; zh: boolean } & Common) {
  const palette = useFigurePalette()
  const end = Math.max(1, ...rows.map((row) => row.end))
  const now = end * 0.55
  return (
    <AcademicFigure id="schedule" index={index} title={zh ? "调度甘特图" : "Schedule"} caption={zh ? "完工等于工期的工序是关键路径。虚线是当前时刻。" : "Jobs that finish at the makespan are on the critical path. The dashed line is now."} plotClass="h-48" rows={rows}>
      <svg viewBox={`0 0 640 ${28 + rows.length * 28}`} className="h-full w-full">
        {rows.map((row, i) => {
          const x = 80 + (row.start / end) * 520
          const w = Math.max(4, ((row.end - row.start) / end) * 520)
          const critical = Math.abs(row.end - end) < 1e-6
          const active = row.id === selected
          return (
            <g key={row.id} onClick={() => onSelect?.(row.id)}>
              <text x="8" y={24 + i * 28} fontSize="12" fill={palette.ink} fontFamily={palette.font}>{row.id}</text>
              <rect x={x} y={10 + i * 28} width={w} height={16} fill={active || critical ? palette.neg : palette.bar} />
              <title>{`${row.id}: ${row.start} → ${row.end}${critical ? " · critical" : ""}`}</title>
            </g>
          )
        })}
        <line x1={80 + (now / end) * 520} x2={80 + (now / end) * 520} y1={4} y2={20 + rows.length * 28} stroke={palette.ink} strokeDasharray="3 2" />
      </svg>
    </AcademicFigure>
  )
}

export function EffectsChart({ effects, index, zh }: { effects: { main: Array<{ name: string; levels: Array<{ x: number; mean: number }> }>; interaction?: { a: string; b: string; low: Array<{ x: number; y: number }>; high: Array<{ x: number; y: number }> } | null }; index: number; zh: boolean }) {
  const palette = useFigurePalette()
  const tick = { fontSize: palette.axisSize, fill: palette.ink, fontFamily: palette.font }
  const first = effects.main[0]
  return (
    <div className="grid gap-2 lg:grid-cols-2">
      {first ? (
        <AcademicFigure id="effects" index={index} title={zh ? "主效应" : "Main effect"} caption={first.name} plotClass="h-48" rows={first.levels}>
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={first.levels}>
              <CartesianGrid stroke={palette.grid} />
              <XAxis dataKey="x" tick={tick} />
              <YAxis dataKey="mean" tick={tick} />
              <Tooltip content={<UnitTip />} />
              <Line dataKey="mean" stroke={palette.bar} dot={false} strokeWidth={palette.weights.data} />
            </LineChart>
          </ResponsiveContainer>
        </AcademicFigure>
      ) : null}
      {effects.interaction ? (
        <AcademicFigure id="interaction" index={index + 1} title={zh ? "交互" : "Interaction"} caption={`${effects.interaction.a} × ${effects.interaction.b}`} plotClass="h-48" rows={[...effects.interaction.low.map((point) => ({ series: "low", ...point })), ...effects.interaction.high.map((point) => ({ series: "high", ...point }))]}>
          <ResponsiveContainer width="100%" height="100%">
            <ScatterChart>
              <CartesianGrid stroke={palette.grid} />
              <XAxis dataKey="x" type="number" tick={tick} />
              <YAxis dataKey="y" type="number" tick={tick} />
              <Tooltip content={<UnitTip />} />
              <Scatter data={effects.interaction.low} fill={palette.bar} />
              <Scatter data={effects.interaction.high} fill={palette.neg} />
            </ScatterChart>
          </ResponsiveContainer>
        </AcademicFigure>
      ) : null}
    </div>
  )
}

function SurfaceMesh({ surface, zLabel }: { surface: { x: number[]; y: number[]; z: number[][] }; zLabel: string }) {
  const ref = useRef<HTMLCanvasElement>(null)
  const palette = useFigurePalette()
  useEffect(() => {
    const canvas = ref.current
    if (!canvas) return
    const ctx = canvas.getContext("2d")
    if (!ctx) return
    const flat = surface.z.flat()
    const low = Math.min(...flat)
    const high = Math.max(...flat)
    ctx.clearRect(0, 0, canvas.width, canvas.height)
    ctx.fillStyle = palette.bg
    ctx.fillRect(0, 0, canvas.width, canvas.height)
    const rows = surface.z.length
    const cols = surface.z[0]?.length || 0
    const project = (i: number, j: number, value: number) => {
      const x = i / Math.max(1, cols - 1)
      const y = j / Math.max(1, rows - 1)
      const z = (value - low) / (high - low || 1)
      return [48 + (x - y) * 130, 200 - (x + y) * 42 - z * 100]
    }
    const paint = (quad: number[][], fill: string, alpha = 1) => {
      ctx.beginPath()
      ctx.moveTo(quad[0][0], quad[0][1])
      quad.slice(1).forEach((point) => ctx.lineTo(point[0], point[1]))
      ctx.closePath()
      ctx.globalAlpha = alpha
      ctx.fillStyle = fill
      ctx.fill()
      ctx.globalAlpha = 1
    }
    for (let j = 0; j < rows - 1; j += 1) {
      for (let i = 0; i < cols - 1; i += 1) {
        const t = (surface.z[j][i] - low) / (high - low || 1)
        paint([project(i, j, low), project(i + 1, j, low), project(i + 1, j + 1, low), project(i, j + 1, low)], colormap("cividis", t), 0.35)
      }
    }
    for (let level = 1; level <= 5; level += 1) {
      const target = low + ((high - low) * level) / 6
      ctx.beginPath()
      for (let j = 0; j < rows; j += 1) {
        for (let i = 0; i < cols - 1; i += 1) {
          const left = surface.z[j][i]
          const right = surface.z[j][i + 1]
          if ((left - target) * (right - target) > 0) continue
          const t = (target - left) / (right - left || 1)
          const [x, y] = project(i + t, j, low)
          ctx.lineTo(x, y)
        }
      }
      ctx.strokeStyle = palette.ink
      ctx.globalAlpha = 0.45
      ctx.stroke()
      ctx.globalAlpha = 1
    }
    for (let j = rows - 2; j >= 0; j -= 1) {
      for (let i = 0; i < cols - 1; i += 1) {
        const quad = [project(i, j, surface.z[j][i]), project(i + 1, j, surface.z[j][i + 1]), project(i + 1, j + 1, surface.z[j + 1][i + 1]), project(i, j + 1, surface.z[j + 1][i])]
        const t = (surface.z[j][i] - low) / (high - low || 1)
        paint(quad, colormap("viridis", t), 0.92)
        ctx.strokeStyle = "rgba(255,255,255,0.2)"
        ctx.stroke()
      }
    }
    for (let step = 0; step < 40; step += 1) {
      ctx.fillStyle = colormap("viridis", 1 - step / 39)
      ctx.fillRect(390, 28 + step * 3.4, 12, 3.6)
    }
    ctx.fillStyle = palette.ink
    ctx.font = `11px ${palette.font}`
    ctx.fillText(zLabel, 368, 18)
    ctx.fillStyle = palette.muted
    ctx.font = `10px ${palette.font}`
    ctx.fillText(high.toPrecision(3), 406, 36)
    ctx.fillText(low.toPrecision(3), 406, 168)
  }, [palette, surface, zLabel])
  return <canvas ref={ref} width={460} height={260} className="h-full w-full" />
}

function ProjectedCloud({ points, index, zh, selected, onSelect }: { points: Array<{ id: string; x: number; y: number; z: number }>; index: number; zh: boolean; selected?: string | null; onSelect?: (id: string) => void }) {
  const palette = useFigurePalette()
  const place = (point: { x: number; y: number; z: number }) => [48 + point.x * 7 - point.y * 3, 176 - point.y * 6 - point.z * 5] as const
  return (
    <AcademicFigure id="pareto-3d" index={index} title={zh ? "三维帕累托" : "Pareto in 3D"} caption={zh ? "斜投影。竖线落到 f3 = 0 的底面。" : "Oblique projection. Drop lines meet the f3 = 0 floor."}>
      <svg viewBox="0 0 320 220" className="h-full w-full">
        <rect width="320" height="220" fill={palette.bg} />
        {points.map((point) => {
          const [x, y] = place(point)
          const [fx, fy] = place({ ...point, z: 0 })
          const hot = point.id === selected
          return (
            <g key={point.id} onClick={() => onSelect?.(point.id)}>
              <line x1={x} y1={y} x2={fx} y2={fy} stroke={palette.grid} />
              <circle cx={fx} cy={fy} r={2} fill={palette.muted} />
              <circle cx={x} cy={y} r={hot ? 5 : 3.2} fill={hot ? palette.neg : palette.bar} />
              <title>{`${point.x.toPrecision(4)}, ${point.y.toPrecision(4)}, ${point.z.toPrecision(4)}`}</title>
            </g>
          )
        })}
      </svg>
    </AcademicFigure>
  )
}

function UnitTip({ active, payload, units }: { active?: boolean; payload?: { name?: string; value?: unknown; unit?: string }[]; units?: Record<string, string> }) {
  if (!active || !payload?.length) return null
  return (
    <div className="fig-tip">
      {payload.map((item) => {
        const unit = item.unit || (item.name ? units?.[item.name] : "") || ""
        const value = Number(item.value)
        return <div key={item.name}>{item.name}: {Number.isFinite(value) ? value.toPrecision(4) : String(item.value)}{unit ? ` ${unit}` : ""}</div>
      })}
    </div>
  )
}

function pointId(row: unknown) {
  if (!row || typeof row !== "object" || !("id" in row)) return ""
  const id = (row as { id?: unknown }).id
  return typeof id === "string" ? id : ""
}

function keysOf(points: StudyPoint[]) {
  const keys: string[] = []
  for (const point of points) {
    for (const key of Object.keys(point.values || {})) if (!keys.includes(key)) keys.push(key)
    for (const key of Object.keys(point.objectives || {})) if (!keys.includes(key) && typeof point.objectives?.[key] === "number") keys.push(key)
  }
  return keys.slice(0, 8)
}

function rotateKey(keys: string[], index: number) {
  const next = [...keys]
  const [item] = next.splice(index, 1)
  next.push(item)
  return next
}

function indexHue(id: string) {
  return [...id].reduce((sum, char) => sum + char.charCodeAt(0), 0)
}

function numberOf(point: StudyPoint, key: string) {
  const value = point.values?.[key] ?? point.objectives?.[key]
  return typeof value === "number" ? value : 0
}

function keyRanges(points: StudyPoint[], keys: string[]) {
  const ranges: Record<string, { min: number; max: number }> = {}
  for (const key of keys) {
    const values = points.map((point) => numberOf(point, key))
    ranges[key] = { min: Math.min(...values), max: Math.max(...values) }
  }
  return ranges
}

function inBrush(point: StudyPoint, brush: { key: string; lo: number; hi: number }) {
  const value = numberOf(point, brush.key)
  return value >= brush.lo && value <= brush.hi
}

function tooltipText(point: StudyPoint, keys: string[], units?: Record<string, string>) {
  return keys.map((key) => `${key}: ${numberOf(point, key).toPrecision(4)}${units?.[key] ? ` ${units[key]}` : ""}`).join("\n")
}

function mix(t: number) {
  return colormap("cividis", t)
}

function diverging(value: number) {
  return divergingRdBu(Math.max(-1, Math.min(1, value)))
}
