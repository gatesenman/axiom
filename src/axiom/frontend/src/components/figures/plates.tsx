import { useId, useMemo, useState, type ReactNode } from "react"
import { colormap, divergingRdBu, formatSI, type FigurePalette } from "@/lib/figure-theme"
import { boxStats, contourBands, decimate, ecdf, hypervolume2d, kde, kneePoint, morrisGuides, paretoFront, paretoMask, performanceProfile, type ProfileRecord, type XY } from "@/lib/figure-geometry"

type Tone = { palette: FigurePalette }
type Box = { x: number; y: number; w: number; h: number }

export function Sparkline({ values, palette, width = 120, height = 32 }: { values: number[] } & Tone & { width?: number; height?: number }) {
  const nums = values.filter((value) => Number.isFinite(value))
  if (nums.length < 2) return null
  const lo = Math.min(...nums)
  const hi = Math.max(...nums)
  const d = nums.map((value, index) => {
    const x = (index / (nums.length - 1)) * width
    const y = height - 4 - ((value - lo) / (hi - lo || 1)) * (height - 8)
    return `${index === 0 ? "M" : "L"}${x.toFixed(1)} ${y.toFixed(1)}`
  }).join(" ")
  const lastY = height - 4 - ((nums.at(-1)! - lo) / (hi - lo || 1)) * (height - 8)
  return (
    <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`} role="img" data-sparkline>
      <path d={`${d} L${width} ${height} L0 ${height} Z`} fill={palette.bar} opacity={0.16} />
      <path d={d} fill="none" stroke={palette.bar} strokeWidth={palette.weights.data} />
      <circle cx={width} cy={lastY} r="2.2" fill={palette.neg} />
    </svg>
  )
}

export function Lollipop({ rows, palette, unit = "" }: { rows: { name: string; value: number }[] } & Tone & { unit?: string }) {
  const ordered = [...rows].sort((a, b) => Math.abs(b.value) - Math.abs(a.value))
  const max = Math.max(1e-9, ...ordered.map((row) => Math.abs(row.value)))
  const width = 560
  const rowH = 26
  const height = 36 + ordered.length * rowH
  return (
    <svg viewBox={`0 0 ${width} ${height}`} className="h-full w-full" role="img" data-plate="lollipop">
      <rect width={width} height={height} fill={palette.bg} />
      <line x1={168} y1={14} x2={168} y2={height - 12} stroke={palette.ink} strokeWidth={palette.weights.axis} />
      {ordered.map((row, index) => {
        const y = 28 + index * rowH
        const x = 168 + (row.value / max) * 300
        return (
          <g key={row.name}>
            <line x1={80} x2={520} y1={y} y2={y} stroke={palette.minor} strokeWidth={palette.weights.minor} />
            <text x={158} y={y + 4} textAnchor="end" fill={palette.ink} fontSize={palette.axisSize} fontFamily={palette.font}>{row.name}</text>
            <line x1={168} y1={y} x2={x} y2={y} stroke={row.value < 0 ? palette.neg : palette.bar} strokeWidth={palette.weights.data} />
            <circle cx={x} cy={y} r={4} fill={row.value < 0 ? palette.neg : palette.bar} stroke={palette.bg} strokeWidth={1} />
            <text x={x + (row.value < 0 ? -10 : 10)} y={y + 4} textAnchor={row.value < 0 ? "end" : "start"} fill={palette.muted} fontSize={11} fontFamily={palette.font}>{formatSI(row.value, unit)}</text>
          </g>
        )
      })}
    </svg>
  )
}

export function ParetoPlate({ points, palette, xLabel, yLabel }: { points: XY[]; xLabel: string; yLabel: string } & Tone) {
  const mask = paretoMask(points, true)
  const front = paretoFront(points, true)
  const knee = kneePoint(front)
  const ref = { x: Math.max(...points.map((point) => point.x)) * 1.05, y: Math.max(...points.map((point) => point.y)) * 1.05 }
  const volume = hypervolume2d(front, ref)
  const frame = useMemo(() => fit(points.concat(ref)), [points])
  const [hover, setHover] = useState<XY | null>(null)
  const [lasso, setLasso] = useState<{ x0: number; y0: number; x1: number; y1: number } | null>(null)
  const width = 560
  const height = 300
  return (
    <svg
      viewBox={`0 0 ${width} ${height}`}
      className="h-full w-full"
      role="img"
      data-plate="pareto"
      onMouseMove={(event) => setHover(eventPoint(event, width, height))}
      onMouseLeave={() => setHover(null)}
      onMouseDown={(event) => {
        const point = eventPoint(event, width, height)
        setLasso({ x0: point.x, y0: point.y, x1: point.x, y1: point.y })
      }}
      onMouseUp={(event) => {
        if (!lasso) return
        const point = eventPoint(event, width, height)
        setLasso({ ...lasso, x1: point.x, y1: point.y })
      }}
      onDoubleClick={() => setLasso(null)}
    >
      <Frame width={width} height={height} palette={palette} xLabel={`${xLabel}  ·  HV ${formatSI(volume)}`} yLabel={yLabel}>
        {(box) => {
          const project = (point: XY) => {
            const x = nx(box, (point.x - frame.x0) / (frame.x1 - frame.x0 || 1))
            const y = ny(box, (point.y - frame.y0) / (frame.y1 - frame.y0 || 1))
            return [x, y] as const
          }
          const shade = [...front, { x: ref.x, y: front.at(-1)?.y ?? ref.y }, ref, { x: front[0]?.x ?? ref.x, y: ref.y }]
          const inside = (point: XY) => {
            if (!lasso) return true
            const [x, y] = project(point)
            const loX = Math.min(lasso.x0, lasso.x1)
            const hiX = Math.max(lasso.x0, lasso.x1)
            const loY = Math.min(lasso.y0, lasso.y1)
            const hiY = Math.max(lasso.y0, lasso.y1)
            if (Math.abs(hiX - loX) < 4 && Math.abs(hiY - loY) < 4) return true
            return x >= loX && x <= hiX && y >= loY && y <= hiY
          }
          return (
            <g>
              <polygon points={shade.map((point) => project(point).join(",")).join(" ")} fill={palette.region} opacity={0.7} />
              <polyline points={front.map((point) => project(point).join(",")).join(" ")} fill="none" stroke={palette.ink} strokeWidth={palette.weights.data} />
              {points.map((point, index) => {
                const [x, y] = project(point)
                const on = mask[index]
                const kept = inside(point)
                return <circle key={`${point.x}-${point.y}-${index}`} cx={x} cy={y} r={on ? 3.6 : 2.6} fill={on ? palette.bar : palette.muted} opacity={kept ? (on ? 1 : 0.35) : 0.12}><title>{`${xLabel} ${formatSI(point.x)}, ${yLabel} ${formatSI(point.y)}`}</title></circle>
              })}
              {knee ? (
                <g>
                  <circle cx={project(knee)[0]} cy={project(knee)[1]} r={6.5} fill="none" stroke={palette.neg} strokeWidth={palette.weights.emphasis} />
                  <line x1={project(knee)[0] + 6} y1={project(knee)[1] - 6} x2={project(knee)[0] + 28} y2={project(knee)[1] - 22} stroke={palette.neg} strokeWidth={palette.weights.axis} />
                  <text x={project(knee)[0] + 32} y={project(knee)[1] - 22} fill={palette.ink} fontSize={11} fontFamily={palette.font}>knee</text>
                </g>
              ) : null}
              {hover ? (
                <g>
                  <line x1={box.x} x2={box.x + box.w} y1={hover.y} y2={hover.y} stroke={palette.muted} strokeWidth={palette.weights.minor} />
                  <line x1={hover.x} x2={hover.x} y1={box.y} y2={box.y + box.h} stroke={palette.muted} strokeWidth={palette.weights.minor} />
                  <text x={box.x + 6} y={box.y + 14} fill={palette.ink} fontSize={11} fontFamily={palette.font}>{readout(hover, box, frame, xLabel, yLabel)}</text>
                </g>
              ) : null}
              {lasso && Math.abs(lasso.x1 - lasso.x0) > 4 ? <rect x={Math.min(lasso.x0, lasso.x1)} y={Math.min(lasso.y0, lasso.y1)} width={Math.abs(lasso.x1 - lasso.x0)} height={Math.abs(lasso.y1 - lasso.y0)} fill={palette.bar} opacity={0.08} stroke={palette.bar} strokeDasharray="3 2" /> : null}
            </g>
          )
        }}
      </Frame>
    </svg>
  )
}

export function ConvergencePlate({ series, palette }: { series: { name: string; points: { t: number; gap: number; lo?: number; hi?: number }[] }[] } & Tone) {
  const flat = series.flatMap((item) => item.points)
  const gaps = flat.map((point) => Math.max(point.gap, 1e-8))
  const x0 = Math.min(...flat.map((point) => point.t))
  const x1 = Math.max(...flat.map((point) => point.t))
  const y0 = Math.log10(Math.min(...gaps))
  const y1 = Math.log10(Math.max(...gaps))
  const width = 560
  const height = 280
  return (
    <svg viewBox={`0 0 ${width} ${height}`} className="h-full w-full" role="img" data-plate="convergence">
      <Frame width={width} height={height} palette={palette} xLabel="t" yLabel="log10 gap">
        {(box) => {
          const project = (t: number, gap: number) => {
            const x = nx(box, (t - x0) / (x1 - x0 || 1))
            const y = ny(box, (Math.log10(Math.max(gap, 1e-8)) - y0) / (y1 - y0 || 1))
            return [x, y] as const
          }
          return (
            <g>
              {series.map((item, index) => {
                const color = palette.categorical[index % palette.categorical.length]
                const band = item.points.filter((point) => point.lo != null && point.hi != null)
                const upper = band.map((point) => project(point.t, point.hi || point.gap).join(","))
                const lower = [...band].reverse().map((point) => project(point.t, point.lo || point.gap).join(","))
                return (
                  <g key={item.name}>
                    {band.length > 1 ? <polygon points={[...upper, ...lower].join(" ")} fill={color} opacity={0.16} /> : null}
                    <polyline points={item.points.map((point) => project(point.t, point.gap).join(",")).join(" ")} fill="none" stroke={color} strokeWidth={palette.weights.data} />
                    {item.points.filter((point, pointIndex) => pointIndex === 0 || point.gap < item.points[pointIndex - 1].gap).map((point) => {
                      const [x, y] = project(point.t, point.gap)
                      return <circle key={`${item.name}-${point.t}`} cx={x} cy={y} r={2.6} fill={palette.bg} stroke={color} strokeWidth={palette.weights.data} />
                    })}
                  </g>
                )
              })}
              <Legend palette={palette} x={box.x + box.w - 72} y={box.y + 12} items={series.map((item, index) => ({ label: item.name, color: palette.categorical[index % palette.categorical.length] }))} />
            </g>
          )
        }}
      </Frame>
    </svg>
  )
}

export function DistributionPlate({ values, palette, unit = "" }: { values: number[]; unit?: string } & Tone) {
  const density = kde(values, 48)
  const cdf = ecdf(values)
  const marks = boxStats(values)
  const bins = histogram(values, 12)
  const maxCount = Math.max(1, ...bins.map((bin) => bin.count))
  const maxDensity = Math.max(...density.map((point) => point.y), 1e-9)
  const lo = Math.min(...values)
  const hi = Math.max(...values)
  const width = 560
  const height = 280
  return (
    <svg viewBox={`0 0 ${width} ${height}`} className="h-full w-full" role="img" data-plate="distribution">
      <Frame width={width} height={height} palette={palette} xLabel={unit || "value"} yLabel="count / CDF">
        {(box) => {
          const xOf = (value: number) => nx(box, (value - lo) / (hi - lo || 1))
          return (
            <g>
              {bins.map((bin) => {
                const x = xOf(bin.lo)
                const w = Math.max(1.5, xOf(bin.hi) - x - 1)
                const h = (bin.count / maxCount) * box.h
                return <rect key={bin.lo} x={x} y={box.y + box.h - h} width={w} height={h} fill={palette.bar} opacity={0.32} />
              })}
              <polyline points={density.map((point) => `${xOf(point.x)},${ny(box, point.y / maxDensity)}`).join(" ")} fill="none" stroke={palette.ink} strokeWidth={palette.weights.data} />
              <polyline points={cdf.map((point) => `${xOf(point.x)},${ny(box, point.y)}`).join(" ")} fill="none" stroke={palette.neg} strokeWidth={palette.weights.data} strokeDasharray="4 3" />
              {([["p05", marks.p05], ["p50", marks.mid], ["p95", marks.p95]] as const).map(([label, value]) => (
                <g key={label}>
                  <line x1={xOf(value)} x2={xOf(value)} y1={box.y + box.h - 8} y2={box.y + box.h} stroke={palette.ink} strokeWidth={palette.weights.emphasis} />
                  <text x={xOf(value)} y={box.y + box.h - 12} textAnchor="middle" fill={palette.muted} fontSize={10} fontFamily={palette.font}>{label}</text>
                </g>
              ))}
              <Legend palette={palette} x={box.x + 8} y={box.y + 12} items={[{ label: "KDE", color: palette.ink }, { label: "CDF", color: palette.neg }]} />
            </g>
          )
        }}
      </Frame>
    </svg>
  )
}

export function ViolinPlate({ values, palette, unit = "" }: { values: number[]; unit?: string } & Tone) {
  const density = kde(values, 40)
  const stats = boxStats(values)
  const maxDensity = Math.max(...density.map((point) => point.y), 1e-9)
  const lo = Math.min(...values)
  const hi = Math.max(...values)
  const width = 360
  const height = 240
  return (
    <svg viewBox={`0 0 ${width} ${height}`} className="h-full w-full" role="img" data-plate="violin">
      <Frame width={width} height={height} palette={palette} xLabel="density" yLabel={unit || "value"}>
        {(box) => {
          const yOf = (value: number) => ny(box, (value - lo) / (hi - lo || 1))
          const cx = box.x + box.w * 0.55
          const half = (point: { y: number }) => (point.y / maxDensity) * box.w * 0.28
          const right = density.map((point) => `${cx + half(point)},${yOf(point.x)}`)
          const left = [...density].reverse().map((point) => `${cx - half(point)},${yOf(point.x)}`)
          const q1 = yOf(stats.q1)
          const q3 = yOf(stats.q3)
          return (
            <g>
              <polygon points={[...right, ...left].join(" ")} fill={palette.bar} opacity={0.28} stroke={palette.bar} strokeWidth={palette.weights.data} />
              <line x1={cx} x2={cx} y1={yOf(stats.p05)} y2={yOf(stats.p95)} stroke={palette.ink} strokeWidth={palette.weights.axis} />
              <rect x={cx - 10} y={Math.min(q1, q3)} width={20} height={Math.max(2, Math.abs(q3 - q1))} fill={palette.bg} stroke={palette.ink} strokeWidth={palette.weights.data} />
              <line x1={cx - 10} x2={cx + 10} y1={yOf(stats.mid)} y2={yOf(stats.mid)} stroke={palette.neg} strokeWidth={palette.weights.emphasis} />
              <text x={box.x + 6} y={box.y + 14} fill={palette.muted} fontSize={11} fontFamily={palette.font}>{`p50 ${formatSI(stats.mid, unit)}`}</text>
            </g>
          )
        }}
      </Frame>
    </svg>
  )
}

export function ProfilePlate({ records, palette }: { records: ProfileRecord[] } & Tone) {
  const curves = performanceProfile(records)
  const tauMax = Math.max(1.01, ...curves.flatMap((curve) => curve.curve.map((point) => point.tau)))
  const width = 560
  const height = 260
  return (
    <svg viewBox={`0 0 ${width} ${height}`} className="h-full w-full" role="img" data-plate="profile">
      <Frame width={width} height={height} palette={palette} xLabel="τ" yLabel="ρ(τ)">
        {(box) => (
          <g>
            {curves.map((curve, index) => (
              <polyline key={curve.solver} points={curve.curve.map((point) => {
                const x = nx(box, (point.tau - 1) / (tauMax - 1 || 1))
                const y = ny(box, point.rho)
                return `${x},${y}`
              }).join(" ")} fill="none" stroke={palette.categorical[index % palette.categorical.length]} strokeWidth={palette.weights.data} />
            ))}
            <Legend palette={palette} x={box.x + box.w - 64} y={box.y + box.h - 14 - curves.length * 14} items={curves.map((curve, index) => ({ label: curve.solver, color: palette.categorical[index % palette.categorical.length] }))} />
          </g>
        )}
      </Frame>
    </svg>
  )
}

export function SankeyPlate({ edges, palette }: { edges: { source: string; target: string; value: number }[] } & Tone) {
  const sources = [...new Set(edges.map((edge) => edge.source))]
  const targets = [...new Set(edges.map((edge) => edge.target))]
  const total = edges.reduce((sum, edge) => sum + edge.value, 0) || 1
  let sourceCursor = 36
  let targetCursor = 36
  const sourceY = new Map<string, { y: number; h: number }>()
  const targetY = new Map<string, { y: number; h: number }>()
  for (const name of sources) {
    const h = Math.max(10, (edges.filter((edge) => edge.source === name).reduce((sum, edge) => sum + edge.value, 0) / total) * 190)
    sourceY.set(name, { y: sourceCursor, h })
    sourceCursor += h + 10
  }
  for (const name of targets) {
    const h = Math.max(10, (edges.filter((edge) => edge.target === name).reduce((sum, edge) => sum + edge.value, 0) / total) * 190)
    targetY.set(name, { y: targetCursor, h })
    targetCursor += h + 10
  }
  const usedS = new Map<string, number>()
  const usedT = new Map<string, number>()
  return (
    <svg viewBox="0 0 560 280" className="h-full w-full" role="img" data-plate="sankey">
      <rect width={560} height={280} fill={palette.bg} />
      {edges.map((edge, index) => {
        const source = sourceY.get(edge.source)!
        const target = targetY.get(edge.target)!
        const sh = Math.max(4, (edge.value / total) * 190)
        const y1 = source.y + (usedS.get(edge.source) || 0)
        const y2 = target.y + (usedT.get(edge.target) || 0)
        usedS.set(edge.source, (usedS.get(edge.source) || 0) + sh)
        usedT.set(edge.target, (usedT.get(edge.target) || 0) + sh)
        const color = palette.categorical[index % palette.categorical.length]
        const d = `M 128 ${y1} C 250 ${y1}, 310 ${y2}, 430 ${y2} L 430 ${y2 + sh} C 310 ${y2 + sh}, 250 ${y1 + sh}, 128 ${y1 + sh} Z`
        return <path key={`${edge.source}-${edge.target}`} d={d} fill={color} opacity={0.78}><title>{`${edge.source} → ${edge.target}: ${formatSI(edge.value)}`}</title></path>
      })}
      {sources.map((name) => {
        const node = sourceY.get(name)!
        return <rect key={name} x={114} y={node.y} width={14} height={node.h} fill={palette.ink} />
      })}
      {targets.map((name) => {
        const node = targetY.get(name)!
        return <rect key={name} x={430} y={node.y} width={14} height={node.h} fill={palette.ink} />
      })}
      {sources.map((name) => <text key={`s-${name}`} x={108} y={(sourceY.get(name)?.y || 0) + 14} textAnchor="end" fill={palette.ink} fontSize={12} fontFamily={palette.font}>{name}</text>)}
      {targets.map((name) => <text key={`t-${name}`} x={450} y={(targetY.get(name)?.y || 0) + 14} fill={palette.ink} fontSize={12} fontFamily={palette.font}>{name}</text>)}
    </svg>
  )
}

export function NetworkPlate({ nodes, edges, palette, geo = false }: { nodes: { id: string; lat?: number; lon?: number }[]; edges: { source: string; target: string; value: number }[]; geo?: boolean } & Tone) {
  const placed = new Map<string, [number, number]>()
  const geographic = geo && nodes.every((node) => node.lat != null && node.lon != null)
  const lats = nodes.map((node) => node.lat || 0)
  const lons = nodes.map((node) => node.lon || 0)
  const minLat = Math.min(...lats)
  const maxLat = Math.max(...lats)
  const minLon = Math.min(...lons)
  const maxLon = Math.max(...lons)
  if (geographic) {
    for (const node of nodes) {
      const x = 48 + ((node.lon! - minLon) / (maxLon - minLon || 1)) * 460
      const y = 36 + (1 - (node.lat! - minLat) / (maxLat - minLat || 1)) * 200
      placed.set(node.id, [x, y])
    }
  } else {
    nodes.forEach((node, index) => {
      const angle = (index / Math.max(1, nodes.length)) * Math.PI * 2 - Math.PI / 2
      placed.set(node.id, [280 + Math.cos(angle) * 150, 148 + Math.sin(angle) * 90])
    })
  }
  const max = Math.max(...edges.map((edge) => edge.value), 1)
  return (
    <svg viewBox="0 0 560 280" className="h-full w-full" role="img" data-plate="network">
      <rect width={560} height={280} fill={palette.bg} />
      {geographic ? (
        <g>
          <rect x={40} y={28} width={480} height={216} fill={palette.region} opacity={0.45} stroke={palette.grid} />
          {[0.25, 0.5, 0.75].map((t) => (
            <g key={t}>
              <line x1={40 + t * 480} x2={40 + t * 480} y1={28} y2={244} stroke={palette.grid} strokeWidth={0.6} />
              <line x1={40} x2={520} y1={28 + t * 216} y2={28 + t * 216} stroke={palette.grid} strokeWidth={0.6} />
            </g>
          ))}
          <text x={44} y={270} fill={palette.muted} fontSize={10} fontFamily={palette.font}>{`等距圆柱  ${minLon.toFixed(1)}°–${maxLon.toFixed(1)}°E`}</text>
        </g>
      ) : null}
      {edges.map((edge) => {
        const a = placed.get(edge.source)
        const b = placed.get(edge.target)
        if (!a || !b) return null
        return <line key={`${edge.source}-${edge.target}`} x1={a[0]} y1={a[1]} x2={b[0]} y2={b[1]} stroke={palette.bar} strokeWidth={0.8 + (edge.value / max) * 4.2} opacity={0.85}><title>{`${edge.source} → ${edge.target}: ${formatSI(edge.value)}`}</title></line>
      })}
      {nodes.map((node) => {
        const at = placed.get(node.id) || [0, 0]
        return (
          <g key={node.id}>
            <circle cx={at[0]} cy={at[1]} r={5.5} fill={palette.ink} stroke={palette.bg} strokeWidth={1.5} />
            <text x={at[0] + 8} y={at[1] - 8} fill={palette.ink} fontSize={12} fontFamily={palette.font}>{node.id}</text>
          </g>
        )
      })}
    </svg>
  )
}

export function GanttPlate({ rows, palette, now }: { rows: { id: string; start: number; end: number; lane?: string }[]; now?: number } & Tone) {
  const end = Math.max(...rows.map((row) => row.end), 1)
  const critical = new Set(rows.filter((row) => Math.abs(row.end - end) < 1e-6).map((row) => row.id))
  const height = 28 + rows.length * 28
  return (
    <svg viewBox={`0 0 560 ${height}`} className="h-full w-full" role="img" data-plate="gantt">
      <rect width={560} height={height} fill={palette.bg} />
      {rows.map((row, index) => {
        const x = 108 + (row.start / end) * 420
        const w = Math.max(4, ((row.end - row.start) / end) * 420)
        const y = 16 + index * 28
        const hot = critical.has(row.id)
        return (
          <g key={row.id}>
            <text x={8} y={y + 12} fill={palette.ink} fontSize={11} fontFamily={palette.font}>{row.lane || row.id}</text>
            <rect x={108} y={y} width={420} height={16} fill={palette.minor} />
            <rect x={x} y={y} width={w} height={16} fill={hot ? palette.neg : palette.bar} />
            <title>{`${row.id}: ${formatSI(row.start)}–${formatSI(row.end)}${hot ? " · critical" : ""}`}</title>
          </g>
        )
      })}
      {now != null ? (
        <g>
          <line x1={108 + (now / end) * 420} x2={108 + (now / end) * 420} y1={8} y2={height - 6} stroke={palette.ink} strokeDasharray="3 2" strokeWidth={palette.weights.axis} />
          <text x={112 + (now / end) * 420} y={12} fill={palette.ink} fontSize={10} fontFamily={palette.font}>today</text>
        </g>
      ) : null}
    </svg>
  )
}

export function HeatPlate({ labels, matrix, palette, clustered = false }: { labels: string[]; matrix: number[][]; clustered?: boolean } & Tone) {
  const order = clustered ? clusterSafe(matrix) : labels.map((_, index) => index)
  const n = labels.length
  const cell = 42
  const width = 78 + n * cell + 36
  const height = 36 + n * cell
  return (
    <svg viewBox={`0 0 ${width} ${height}`} className="h-full w-full" role="img" data-plate="heatmap">
      <rect width={width} height={height} fill={palette.bg} />
      {order.map((rowIndex, i) => order.map((colIndex, j) => {
        const value = matrix[rowIndex][colIndex]
        return (
          <g key={`${i}-${j}`}>
            <rect x={64 + j * cell} y={8 + i * cell} width={cell - 3} height={cell - 3} fill={divergingRdBu(value)} />
            <text x={64 + j * cell + (cell - 3) / 2} y={8 + i * cell + 18} textAnchor="middle" fill={Math.abs(value) > 0.55 ? "#f7f7f7" : "#111111"} fontSize={10} fontFamily={palette.font}>{value.toFixed(2)}</text>
          </g>
        )
      }))}
      {order.map((index, slot) => <text key={`r-${labels[index]}`} x={4} y={28 + slot * cell} fill={palette.ink} fontSize={11} fontFamily={palette.font}>{labels[index]}</text>)}
      {order.map((index, slot) => <text key={`c-${labels[index]}`} x={64 + slot * cell + 16} y={height - 4} fill={palette.ink} fontSize={11} fontFamily={palette.font}>{labels[index]}</text>)}
      {Array.from({ length: 11 }, (_, step) => <rect key={step} x={width - 22} y={8 + step * ((n * cell - 8) / 11)} width={10} height={(n * cell - 8) / 11 + 0.4} fill={divergingRdBu(1 - step / 10)} />)}
    </svg>
  )
}

export function SurfacePlate({ palette, zLabel = "f" }: Tone & { zLabel?: string }) {
  const xs = Array.from({ length: 10 }, (_, index) => index)
  const ys = Array.from({ length: 8 }, (_, index) => index)
  const grid = ys.map((y) => xs.map((x) => Math.sin(x / 2.2) * Math.cos(y / 1.8) + 0.12 * x))
  const flat = grid.flat()
  const lo = Math.min(...flat)
  const hi = Math.max(...flat)
  const levels = contourBands(grid, 6)
  const project = (i: number, j: number, value: number) => {
    const x = i / (xs.length - 1)
    const y = j / (ys.length - 1)
    const z = (value - lo) / (hi - lo || 1)
    return [78 + (x - y) * 150, 188 - (x + y) * 42 - z * 78]
  }
  const floor = (i: number, j: number) => project(i, j, lo)
  return (
    <svg viewBox="0 0 460 250" className="h-full w-full" role="img" data-plate="surface">
      <rect width={460} height={250} fill={palette.bg} />
      {ys.slice(0, -1).map((_, j) => xs.slice(0, -1).map((__, i) => {
        const quad = [floor(i, j), floor(i + 1, j), floor(i + 1, j + 1), floor(i, j + 1)]
        const t = (grid[j][i] - lo) / (hi - lo || 1)
        return <polygon key={`f${i}-${j}`} points={quad.map((point) => point.join(",")).join(" ")} fill={colormap("cividis", t)} opacity={0.34} />
      }))}
      {levels.map((level) => (
        <polyline key={level} fill="none" stroke={palette.ink} strokeWidth={0.7} opacity={0.55} points={iso(grid, level).map(([i, j]) => floor(i, j).join(",")).join(" ")} />
      ))}
      {ys.slice(0, -1).map((_, j) => xs.slice(0, -1).map((__, i) => {
        const quad = [project(i, j, grid[j][i]), project(i + 1, j, grid[j][i + 1]), project(i + 1, j + 1, grid[j + 1][i + 1]), project(i, j + 1, grid[j + 1][i])]
        const t = (grid[j][i] - lo) / (hi - lo || 1)
        const light = 0.62 + 0.38 * Math.max(-0.4, Math.min(0.8, (quad[0][1] - quad[2][1]) / 36))
        return <polygon key={`${i}-${j}`} points={quad.map((point) => point.join(",")).join(" ")} fill={colormap("viridis", t)} opacity={Math.min(1, Math.max(0.5, light))} stroke="rgba(255,255,255,0.18)" strokeWidth={0.35} />
      }))}
      {[[2, 2], [6, 3], [8, 5]].map(([i, j]) => {
        const [x, y] = project(i, j, grid[j][i])
        return <circle key={`${i}${j}`} cx={x} cy={y} r={3} fill={palette.bg} stroke={palette.ink} strokeWidth={1.2} />
      })}
      <text x={392} y={28} fill={palette.ink} fontSize={11} fontFamily={palette.font}>{zLabel}</text>
      {Array.from({ length: 40 }, (_, step) => <rect key={step} x={392} y={36 + step * 3.2} width={12} height={3.4} fill={colormap("viridis", 1 - step / 39)} />)}
      <text x={408} y={46} fill={palette.muted} fontSize={10} fontFamily={palette.font}>{formatSI(hi)}</text>
      <text x={408} y={168} fill={palette.muted} fontSize={10} fontFamily={palette.font}>{formatSI(lo)}</text>
    </svg>
  )
}

export function ParallelPlate({ palette }: Tone) {
  const labels = ["成本", "时间", "排放", "质量"]
  const [order, setOrder] = useState([0, 1, 2, 3])
  const lines = [
    [0.2, 0.72, 0.4, 0.55],
    [0.55, 0.42, 0.6, 0.3],
    [0.8, 0.22, 0.9, 0.7],
    [0.35, 0.5, 0.3, 0.48],
    [0.62, 0.84, 0.25, 0.4],
  ]
  const brush = { axis: 1, lo: 0.35, hi: 0.7 }
  const width = 560
  const height = 250
  const top = 36
  const bottom = 220
  return (
    <svg viewBox={`0 0 ${width} ${height}`} className="h-full w-full" role="img" data-plate="parallel">
      <rect width={width} height={height} fill={palette.bg} />
      {order.map((axis, index) => {
        const x = 48 + index * 150
        const label = labels[axis]
        const brushed = axis === brush.axis
        const y0 = top + (1 - brush.hi) * (bottom - top)
        const y1 = top + (1 - brush.lo) * (bottom - top)
        return (
          <g key={label}>
            <line x1={x} x2={x} y1={top} y2={bottom} stroke={palette.ink} strokeWidth={palette.weights.axis} />
            <text x={x} y={18} textAnchor="middle" fill={palette.ink} fontSize={12} fontFamily={palette.font} style={{ cursor: "pointer" }} onClick={() => setOrder((current) => rotate(current, index))}>{label}</text>
            {brushed ? (
              <g>
                <rect x={x - 7} y={y0} width={14} height={y1 - y0} fill={palette.bar} opacity={0.18} />
                <rect x={x - 6} y={y0 - 3} width={12} height={6} fill={palette.bar} />
                <rect x={x - 6} y={y1 - 3} width={12} height={6} fill={palette.bar} />
              </g>
            ) : null}
          </g>
        )
      })}
      {lines.map((line, index) => {
        const d = order.map((axis, slot) => {
          const x = 48 + slot * 150
          const y = top + (1 - line[axis]) * (bottom - top)
          return `${slot === 0 ? "M" : "L"}${x} ${y}`
        }).join(" ")
        const brushed = line[brush.axis] >= brush.lo && line[brush.axis] <= brush.hi
        return <path key={index} d={d} fill="none" stroke={palette.categorical[index % palette.categorical.length]} strokeWidth={brushed ? palette.weights.emphasis : palette.weights.data} opacity={brushed ? 0.95 : 0.16} />
      })}
    </svg>
  )
}

const SOBOL_DEMO = [
  { name: "利润A", s1: 0.42, st: 0.61, ci: 0.05 },
  { name: "工时", s1: 0.21, st: 0.33, ci: 0.04 },
  { name: "原料", s1: 0.11, st: 0.18, ci: 0.03 },
]

export function SobolPlate({ palette, rows = SOBOL_DEMO }: Tone & { rows?: { name: string; s1: number; st: number; ci?: number }[] }) {
  const width = 560
  const height = 260
  const peak = Math.max(1, ...rows.flatMap((row) => [row.s1 + (row.ci || 0), row.st + (row.ci || 0)]))
  return (
    <svg viewBox={`0 0 ${width} ${height}`} className="h-full w-full" role="img" data-plate="sobol">
      <Frame width={width} height={height} palette={palette} xLabel="" yLabel="index">
        {(box) => (
          <g>
            {rows.map((row, index) => {
              const slot = box.w / rows.length
              const x = box.x + index * slot + slot * 0.22
              const s1 = ny(box, row.s1 / peak)
              const st = ny(box, row.st / peak)
              const base = box.y + box.h
              return (
                <g key={row.name}>
                  <rect x={x} y={s1} width={16} height={base - s1} fill={palette.bar} />
                  <rect x={x + 22} y={st} width={16} height={base - st} fill={palette.alt} />
                  {row.ci != null ? (
                    <g>
                      <Whisker x={x + 8} y0={ny(box, (row.s1 - row.ci) / peak)} y1={ny(box, (row.s1 + row.ci) / peak)} palette={palette} />
                      <Whisker x={x + 30} y0={ny(box, (row.st - row.ci) / peak)} y1={ny(box, (row.st + row.ci) / peak)} palette={palette} />
                    </g>
                  ) : null}
                  <text x={x + 18} y={height - 8} textAnchor="middle" fill={palette.ink} fontSize={11} fontFamily={palette.font}>{row.name}</text>
                </g>
              )
            })}
            <Legend palette={palette} x={box.x + box.w - 48} y={box.y + 12} items={[{ label: "S1", color: palette.bar }, { label: "ST", color: palette.alt }]} />
          </g>
        )}
      </Frame>
    </svg>
  )
}

const MORRIS_DEMO = [
  { name: "利润", mu: 1.4, sigma: 0.2 },
  { name: "工时", mu: 0.4, sigma: 1.1 },
  { name: "原料", mu: 1.1, sigma: 0.9 },
  { name: "需求", mu: 0.3, sigma: 0.25 },
]

export function MorrisPlate({ palette, rows = MORRIS_DEMO }: Tone & { rows?: { name: string; mu: number; sigma: number }[] }) {
  const guides = morrisGuides(rows.map((row) => ({ mu: row.mu, sigma: row.sigma })))
  const x1 = Math.max(guides.mu * 1.4, ...rows.map((row) => row.mu)) * 1.15
  const y1 = Math.max(guides.sigma * 1.4, ...rows.map((row) => row.sigma)) * 1.15
  const width = 520
  const height = 260
  return (
    <svg viewBox={`0 0 ${width} ${height}`} className="h-full w-full" role="img" data-plate="morris">
      <Frame width={width} height={height} palette={palette} xLabel="μ*" yLabel="σ">
        {(box) => {
          const project = (mu: number, sigma: number) => [nx(box, mu / (x1 || 1)), ny(box, sigma / (y1 || 1))] as const
          const [gx] = project(guides.mu, 0)
          const [, gy] = project(0, guides.sigma)
          return (
            <g>
              <line x1={gx} x2={gx} y1={box.y} y2={box.y + box.h} stroke={palette.muted} strokeDasharray="3 2" strokeWidth={palette.weights.grid} />
              <line x1={box.x} x2={box.x + box.w} y1={gy} y2={gy} stroke={palette.muted} strokeDasharray="3 2" strokeWidth={palette.weights.grid} />
              <text x={box.x + 6} y={box.y + 14} fill={palette.muted} fontSize={10} fontFamily={palette.font}>非线性 / 交互</text>
              <text x={gx + 6} y={box.y + 14} fill={palette.muted} fontSize={10} fontFamily={palette.font}>交互</text>
              <text x={box.x + 6} y={gy + 14} fill={palette.muted} fontSize={10} fontFamily={palette.font}>可忽略</text>
              <text x={gx + 6} y={gy + 14} fill={palette.muted} fontSize={10} fontFamily={palette.font}>线性</text>
              {rows.map((row, index) => {
                const [x, y] = project(row.mu, row.sigma)
                return (
                  <g key={row.name}>
                    <circle cx={x} cy={y} r={4.5} fill={palette.categorical[index % palette.categorical.length]} stroke={palette.bg} strokeWidth={1} />
                    <text x={x + 7} y={y - 6} fill={palette.ink} fontSize={11} fontFamily={palette.font}>{row.name}</text>
                  </g>
                )
              })}
            </g>
          )
        }}
      </Frame>
    </svg>
  )
}

export function N2Plate({ palette }: Tone) {
  const marker = useId().replace(/:/g, "")
  const labels = ["结构", "气动", "推进", "性能"]
  const cells = [
    [0, 1, 0, 1],
    [1, 0, 1, 0],
    [0, 1, 0, 1],
    [1, 0, 1, 0],
  ]
  const size = 52
  return (
    <svg viewBox={`0 0 ${48 + labels.length * (size + 8)} ${36 + labels.length * (size + 8)}`} className="h-full w-full" role="img" data-plate="n2">
      <rect width="100%" height="100%" fill={palette.bg} />
      {labels.map((label, index) => <text key={label} x={64 + index * (size + 8)} y={16} textAnchor="middle" fill={palette.ink} fontSize={12} fontFamily={palette.font}>{label}</text>)}
      {cells.map((row, i) => row.map((value, j) => (
        <g key={`${i}-${j}`}>
          <rect x={40 + j * (size + 8)} y={28 + i * (size + 8)} width={size} height={size} fill={i === j ? palette.categorical[i % palette.categorical.length] : value ? palette.region : palette.bg} stroke={palette.grid} />
          {value && i !== j ? <path d={`M ${52 + j * (size + 8)} ${54 + i * (size + 8)} l 22 -10`} stroke={palette.neg} strokeWidth={1.3} markerEnd={`url(#${marker})`} /> : null}
          <title>{value && i !== j ? `${labels[j]} → ${labels[i]}` : labels[i]}</title>
        </g>
      )))}
      <defs>
        <marker id={marker} markerWidth="6" markerHeight="6" refX="5" refY="3" orient="auto">
          <path d="M0,0 L6,3 L0,6 Z" fill={palette.neg} />
        </marker>
      </defs>
    </svg>
  )
}

const TORNADO_DEMO = [
  { name: "利润A", down: -180, up: 240 },
  { name: "工时", down: -90, up: 70 },
  { name: "原料", down: -40, up: 30 },
]

export function TornadoPlate({ palette, rows = TORNADO_DEMO, unit = "" }: Tone & { rows?: { name: string; down: number; up: number }[]; unit?: string }) {
  const max = Math.max(...rows.flatMap((row) => [Math.abs(row.down), Math.abs(row.up)]), 1)
  const height = 36 + rows.length * 36
  return (
    <svg viewBox={`0 0 560 ${height}`} className="h-full w-full" role="img" data-plate="tornado">
      <rect width={560} height={height} fill={palette.bg} />
      <line x1={250} x2={250} y1={12} y2={height - 16} stroke={palette.ink} strokeWidth={palette.weights.axis} />
      <text x={250} y={height - 2} textAnchor="middle" fill={palette.muted} fontSize={11} fontFamily={palette.font}>base</text>
      {rows.map((row, index) => {
        const y = 18 + index * 36
        const x0 = 250 + (row.down / max) * 200
        const x1 = 250 + (row.up / max) * 200
        return (
          <g key={row.name}>
            <text x={8} y={y + 13} fill={palette.ink} fontSize={12} fontFamily={palette.font}>{row.name}</text>
            <rect x={x0} y={y} width={250 - x0} height={18} fill={palette.neg} />
            <rect x={250} y={y} width={x1 - 250} height={18} fill={palette.bar} />
            <text x={x0 - 4} y={y + 13} textAnchor="end" fill={palette.muted} fontSize={10} fontFamily={palette.font}>{formatSI(row.down, unit)}</text>
            <text x={x1 + 4} y={y + 13} fill={palette.muted} fontSize={10} fontFamily={palette.font}>{formatSI(row.up, unit)}</text>
          </g>
        )
      })}
    </svg>
  )
}

export function FeasiblePlate({ palette }: Tone) {
  const width = 520
  const height = 260
  const poly = [[0.12, 0.16], [0.34, 0.82], [0.7, 0.74], [0.86, 0.22]]
  return (
    <svg viewBox={`0 0 ${width} ${height}`} className="h-full w-full" role="img" data-plate="feasible">
      <Frame width={width} height={height} palette={palette} xLabel="x" yLabel="y">
        {(box) => {
          const at = (point: number[]) => `${nx(box, point[0])},${ny(box, point[1])}`
          const edge = (a: number[], b: number[], label: string) => {
            const x = (nx(box, a[0]) + nx(box, b[0])) / 2
            const y = (ny(box, a[1]) + ny(box, b[1])) / 2
            const angle = Math.atan2(ny(box, b[1]) - ny(box, a[1]), nx(box, b[0]) - nx(box, a[0])) * 180 / Math.PI
            return <text x={x} y={y - 6} fill={palette.ink} fontSize={11} fontFamily={palette.font} textAnchor="middle" transform={`rotate(${angle} ${x} ${y - 6})`}>{label}</text>
          }
          return (
            <g>
              <polygon points={poly.map(at).join(" ")} fill={palette.region} stroke="none" />
              <line x1={nx(box, poly[0][0])} y1={ny(box, poly[0][1])} x2={nx(box, poly[1][0])} y2={ny(box, poly[1][1])} stroke={palette.ink} strokeWidth={palette.weights.emphasis} />
              <line x1={nx(box, poly[1][0])} y1={ny(box, poly[1][1])} x2={nx(box, poly[2][0])} y2={ny(box, poly[2][1])} stroke={palette.ink} strokeWidth={palette.weights.emphasis} />
              <line x1={nx(box, poly[2][0])} y1={ny(box, poly[2][1])} x2={nx(box, poly[3][0])} y2={ny(box, poly[3][1])} stroke={palette.muted} strokeWidth={palette.weights.data} />
              <line x1={nx(box, poly[3][0])} y1={ny(box, poly[3][1])} x2={nx(box, poly[0][0])} y2={ny(box, poly[0][1])} stroke={palette.muted} strokeWidth={palette.weights.data} />
              <line x1={nx(box, 0.18)} y1={ny(box, 0.28)} x2={nx(box, 0.78)} y2={ny(box, 0.62)} stroke={palette.neg} strokeDasharray="4 3" />
              <line x1={nx(box, 0.22)} y1={ny(box, 0.18)} x2={nx(box, 0.9)} y2={ny(box, 0.55)} stroke={palette.neg} strokeDasharray="4 3" />
              <text x={nx(box, 0.72)} y={ny(box, 0.66)} fill={palette.neg} fontSize={10} fontFamily={palette.font}>f</text>
              {edge(poly[0], poly[1], "原料")}
              {edge(poly[1], poly[2], "工时")}
              <circle cx={nx(box, poly[1][0])} cy={ny(box, poly[1][1])} r={4.5} fill={palette.ink} />
              <rect x={nx(box, poly[1][0]) + 10} y={ny(box, poly[1][1]) - 28} width={72} height={18} fill={palette.bg} stroke={palette.ink} />
              <text x={nx(box, poly[1][0]) + 16} y={ny(box, poly[1][1]) - 15} fill={palette.ink} fontSize={11} fontFamily={palette.font}>最优顶点</text>
              <line x1={nx(box, poly[1][0]) + 4} y1={ny(box, poly[1][1]) - 4} x2={nx(box, poly[1][0]) + 10} y2={ny(box, poly[1][1]) - 18} stroke={palette.ink} strokeWidth={palette.weights.axis} />
            </g>
          )
        }}
      </Frame>
    </svg>
  )
}

export function Composer({ children, palette }: { children: { key: string; node: ReactNode }[] } & Tone) {
  return (
    <div className="grid gap-3 md:grid-cols-2" data-plate="composer" style={{ background: palette.bg, color: palette.ink, fontFamily: palette.font }}>
      {children.map((child, index) => (
        <div key={child.key} className="relative border p-2 pt-6" style={{ borderColor: palette.grid }}>
          <span className="absolute top-1 left-2 text-[12px] font-medium">({String.fromCharCode(97 + index)})</span>
          {child.node}
        </div>
      ))}
    </div>
  )
}

export function CloudNote({ count, palette }: { count: number } & Tone) {
  const points = useMemo(() => decimate(Array.from({ length: count }, (_, index) => ({ x: index, y: Math.sin(index / 30) })), 300), [count])
  const frame = fit(points)
  const width = 560
  const height = 160
  return (
    <svg viewBox={`0 0 ${width} ${height}`} className="h-28 w-full" role="img" data-plate="cloud">
      <Frame width={width} height={height} palette={palette} xLabel="i" yLabel="y">
        {(box) => (
          <g>
            <polyline points={points.map((point) => {
              const x = nx(box, (point.x - frame.x0) / (frame.x1 - frame.x0 || 1))
              const y = ny(box, (point.y - frame.y0) / (frame.y1 - frame.y0 || 1))
              return `${x},${y}`
            }).join(" ")} fill="none" stroke={palette.bar} strokeWidth={palette.weights.data} />
            <text x={box.x + 8} y={box.y + 16} fill={palette.muted} fontSize={11} fontFamily={palette.font}>{`${count.toLocaleString()} → ${points.length}`}</text>
          </g>
        )}
      </Frame>
    </svg>
  )
}

function Frame({ width, height, palette, xLabel, yLabel, children }: { width: number; height: number; palette: FigurePalette; xLabel: string; yLabel: string; children: (box: Box) => ReactNode }) {
  const box = plotBox(width, height)
  const majors = 4
  return (
    <g>
      <rect width={width} height={height} fill={palette.bg} />
      {Array.from({ length: majors - 1 }, (_, index) => {
        const y = ny(box, (index + 1) / majors)
        return <line key={index} x1={box.x} x2={box.x + box.w} y1={y} y2={y} stroke={palette.grid} strokeWidth={palette.weights.grid} />
      })}
      <rect x={box.x} y={box.y} width={box.w} height={box.h} fill="none" stroke={palette.ink} strokeWidth={palette.weights.axis} />
      {Array.from({ length: majors + 1 }, (_, index) => {
        const t = index / majors
        const x = nx(box, t)
        const y = ny(box, t)
        return (
          <g key={`tick-${index}`}>
            <line x1={x} x2={x} y1={box.y + box.h} y2={box.y + box.h + 4} stroke={palette.ink} strokeWidth={palette.weights.axis} />
            <line x1={box.x - 4} x2={box.x} y1={y} y2={y} stroke={palette.ink} strokeWidth={palette.weights.axis} />
            {index < majors ? [0.25, 0.5, 0.75].map((step) => (
              <line key={step} x1={nx(box, t + step / majors)} x2={nx(box, t + step / majors)} y1={box.y + box.h} y2={box.y + box.h + 2} stroke={palette.muted} strokeWidth={palette.weights.minor} />
            )) : null}
          </g>
        )
      })}
      <text x={box.x + box.w / 2} y={height - 8} textAnchor="middle" fill={palette.muted} fontSize={palette.axisSize} fontFamily={palette.font}>{xLabel}</text>
      <text x={13} y={box.y + box.h / 2} textAnchor="middle" fill={palette.muted} fontSize={palette.axisSize} fontFamily={palette.font} transform={`rotate(-90 13 ${box.y + box.h / 2})`}>{yLabel}</text>
      {children(box)}
    </g>
  )
}

function Legend({ items, palette, x, y }: { items: { label: string; color: string }[]; palette: FigurePalette; x: number; y: number }) {
  return (
    <g>
      {items.map((item, index) => (
        <g key={item.label} transform={`translate(0 ${index * 14})`}>
          <line x1={x} x2={x + 16} y1={y} y2={y} stroke={item.color} strokeWidth={palette.weights.data} />
          <text x={x + 20} y={y + 3} fill={palette.ink} fontSize={11} fontFamily={palette.font}>{item.label}</text>
        </g>
      ))}
    </g>
  )
}

function Whisker({ x, y0, y1, palette }: { x: number; y0: number; y1: number; palette: FigurePalette }) {
  const top = Math.min(y0, y1)
  const bottom = Math.max(y0, y1)
  return (
    <g>
      <line x1={x} x2={x} y1={top} y2={bottom} stroke={palette.ink} strokeWidth={palette.weights.axis} />
      <line x1={x - 4} x2={x + 4} y1={top} y2={top} stroke={palette.ink} strokeWidth={palette.weights.axis} />
      <line x1={x - 4} x2={x + 4} y1={bottom} y2={bottom} stroke={palette.ink} strokeWidth={palette.weights.axis} />
    </g>
  )
}

function plotBox(width: number, height: number): Box {
  return { x: 46, y: 16, w: Math.max(40, width - 64), h: Math.max(40, height - 46) }
}

function nx(box: Box, t: number) {
  return box.x + Math.min(1, Math.max(0, t)) * box.w
}

function ny(box: Box, t: number) {
  return box.y + (1 - Math.min(1, Math.max(0, t))) * box.h
}

function fit(points: XY[]) {
  const xs = points.map((point) => point.x)
  const ys = points.map((point) => point.y)
  const padX = (Math.max(...xs) - Math.min(...xs)) * 0.08 || 1
  const padY = (Math.max(...ys) - Math.min(...ys)) * 0.08 || 1
  return { x0: Math.min(...xs) - padX, x1: Math.max(...xs) + padX, y0: Math.min(...ys) - padY, y1: Math.max(...ys) + padY }
}

function histogram(values: number[], bins: number) {
  const lo = Math.min(...values)
  const hi = Math.max(...values)
  const width = (hi - lo) / bins || 1
  return Array.from({ length: bins }, (_, index) => {
    const start = lo + index * width
    const end = index === bins - 1 ? hi + 1e-9 : start + width
    return { lo: start, hi: end, count: values.filter((value) => value >= start && value < end).length }
  })
}

function clusterSafe(matrix: number[][]) {
  const order = matrix.map((_, index) => index)
  return order.sort((a, b) => matrix[a].reduce((sum, value) => sum + value, 0) - matrix[b].reduce((sum, value) => sum + value, 0))
}

function iso(grid: number[][], level: number) {
  const points: [number, number][] = []
  for (let j = 0; j < grid.length; j += 1) {
    for (let i = 0; i < grid[j].length - 1; i += 1) {
      const left = grid[j][i]
      const right = grid[j][i + 1]
      if ((left - level) * (right - level) <= 0) points.push([i + (level - left) / (right - left || 1), j])
    }
  }
  return points
}

function rotate(order: number[], index: number) {
  const next = [...order]
  const [item] = next.splice(index, 1)
  next.push(item)
  return next
}

function eventPoint(event: { clientX: number; clientY: number; currentTarget: EventTarget & { getBoundingClientRect(): DOMRect } }, width: number, height: number) {
  const rect = event.currentTarget.getBoundingClientRect()
  return {
    x: ((event.clientX - rect.left) / Math.max(rect.width, 1)) * width,
    y: ((event.clientY - rect.top) / Math.max(rect.height, 1)) * height,
  }
}

function readout(hover: XY, box: Box, frame: { x0: number; x1: number; y0: number; y1: number }, xLabel: string, yLabel: string) {
  const x = frame.x0 + ((hover.x - box.x) / box.w) * (frame.x1 - frame.x0)
  const y = frame.y0 + (1 - (hover.y - box.y) / box.h) * (frame.y1 - frame.y0)
  return `${xLabel} ${formatSI(x)}   ${yLabel} ${formatSI(y)}`
}

export function useGalleryRecords() {
  return useMemo<ProfileRecord[]>(() => [
    { solver: "HiGHS", problem: "mix", time: 0.02 },
    { solver: "SCIP", problem: "mix", time: 0.04 },
    { solver: "CBC", problem: "mix", time: 0.05 },
    { solver: "HiGHS", problem: "diet", time: 0.03 },
    { solver: "SCIP", problem: "diet", time: 0.02 },
    { solver: "CBC", problem: "diet", time: 0.06 },
  ], [])
}
