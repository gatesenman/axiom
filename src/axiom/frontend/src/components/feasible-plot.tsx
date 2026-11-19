import { useMemo, useState } from "react"
import { useFigurePalette } from "@/components/figures/theme"

type Region = {
  x: string
  y: string
  polygon: number[][]
  lines?: { name: string; points: number[][] }[]
  optimum?: { x?: number | null; y?: number | null } | null
}

export function FeasiblePlot({ region }: { region: Region }) {
  const palette = useFigurePalette()
  const fitted = useMemo(() => bounds(region.polygon), [region])
  const [window, setWindow] = useState<{ x0: number; x1: number; y0: number; y1: number } | null>(null)
  const [drag, setDrag] = useState<{ x: number; y: number } | null>(null)
  const [cursor, setCursor] = useState<{ x: number; y: number } | null>(null)
  const [readout, setReadout] = useState("")
  const frame = window || fitted
  const width = 560
  const height = 320
  const pad = { left: 48, right: 16, top: 16, bottom: 36 }

  function project(x: number, y: number) {
    const px = pad.left + ((x - frame.x0) / Math.max(frame.x1 - frame.x0, 1e-9)) * (width - pad.left - pad.right)
    const py = pad.top + (1 - (y - frame.y0) / Math.max(frame.y1 - frame.y0, 1e-9)) * (height - pad.top - pad.bottom)
    return [px, py]
  }

  function unproject(px: number, py: number) {
    const x = frame.x0 + ((px - pad.left) / (width - pad.left - pad.right)) * (frame.x1 - frame.x0)
    const y = frame.y0 + (1 - (py - pad.top) / (height - pad.top - pad.bottom)) * (frame.y1 - frame.y0)
    return [x, y]
  }

  const poly = region.polygon.map(([x, y]) => project(x, y).join(",")).join(" ")
  const optimum = region.optimum && region.optimum.x != null && region.optimum.y != null ? project(region.optimum.x, region.optimum.y) : null

  function describe(px: number, py: number) {
    const [mx, my] = unproject(px, py)
    let nearest = ""
    let best = 16
    for (const line of region.lines || []) {
      const [a, b] = line.points
      if (!a || !b) continue
      const [x1, y1] = project(a[0], a[1])
      const [x2, y2] = project(b[0], b[1])
      const distance = segmentDistance(px, py, x1, y1, x2, y2)
      if (distance < best) {
        best = distance
        nearest = line.name
      }
    }
    const point = `${region.x} = ${trim(mx)}, ${region.y} = ${trim(my)}`
    return nearest ? `${nearest}: ${point}` : point
  }

  return (
    <div className="relative h-full">
    <svg
      viewBox={`0 0 ${width} ${height}`}
      className="h-full w-full"
      role="img"
      onDoubleClick={() => { setWindow(null); setReadout("") }}
      onPointerLeave={() => { if (!drag) setReadout("") }}
      onPointerDown={(event) => {
        const point = relative(event.currentTarget, event.clientX, event.clientY)
        setDrag({ x: point[0], y: point[1] })
        setCursor(null)
      }}
      onPointerMove={(event) => {
        const point = relative(event.currentTarget, event.clientX, event.clientY)
        if (drag) {
          setCursor({ x: point[0], y: point[1] })
          return
        }
        setReadout(describe(point[0], point[1]))
      }}
      onPointerUp={(event) => {
        if (!drag) return
        const point = relative(event.currentTarget, event.clientX, event.clientY)
        const [x0, y0] = unproject(Math.min(drag.x, point[0]), Math.max(drag.y, point[1]))
        const [x1, y1] = unproject(Math.max(drag.x, point[0]), Math.min(drag.y, point[1]))
        if (Math.abs(point[0] - drag.x) > 8 && Math.abs(point[1] - drag.y) > 8 && x1 > x0 && y1 > y0) {
          setWindow({ x0, x1, y0, y1 })
        }
        setDrag(null)
        setCursor(null)
      }}
    >
      <rect x={pad.left} y={pad.top} width={width - pad.left - pad.right} height={height - pad.top - pad.bottom} fill={palette.bg} stroke={palette.grid} />
      {[0, 0.5, 1].map((t) => {
        const x = frame.x0 + t * (frame.x1 - frame.x0)
        const y = frame.y0 + t * (frame.y1 - frame.y0)
        const [px] = project(x, frame.y0)
        const [, py] = project(frame.x0, y)
        return (
          <g key={t}>
            <line x1={px} y1={pad.top} x2={px} y2={height - pad.bottom} stroke={palette.grid} strokeWidth={palette.weights.grid} />
            <line x1={pad.left} y1={py} x2={width - pad.right} y2={py} stroke={palette.grid} strokeWidth={palette.weights.grid} />
            <text x={px} y={height - 16} textAnchor="middle" fill={palette.ink} fontSize={palette.axisSize} fontFamily={palette.font}>{trim(x)}</text>
            <text x={pad.left - 6} y={py + 4} textAnchor="end" fill={palette.ink} fontSize={palette.axisSize} fontFamily={palette.font}>{trim(y)}</text>
          </g>
        )
      })}
      <polygon points={poly} fill={palette.region} stroke={palette.bar} strokeWidth={palette.weights.data} />
      {optimum && region.optimum?.x != null && region.optimum?.y != null ? isoLines(region.polygon, region.optimum.x, region.optimum.y).map((line, index) => {
        const [x1, y1] = project(line[0][0], line[0][1])
        const [x2, y2] = project(line[1][0], line[1][1])
        return <line key={index} x1={x1} y1={y1} x2={x2} y2={y2} stroke={palette.neg} strokeDasharray="4 3" strokeWidth={palette.weights.grid} />
      }) : null}
      {(region.lines || []).map((line) => {
        const [a, b] = line.points
        if (!a || !b) return null
        const [x1, y1] = project(a[0], a[1])
        const [x2, y2] = project(b[0], b[1])
        const binding = optimum ? segmentDistance(optimum[0], optimum[1], x1, y1, x2, y2) < 8 : false
        return (
          <g key={line.name}>
            <line x1={x1} y1={y1} x2={x2} y2={y2} stroke={binding ? palette.ink : palette.line} strokeWidth={binding ? palette.weights.emphasis : palette.weights.data}>
              <title>{line.name}</title>
            </line>
            <text x={(x1 + x2) / 2} y={(y1 + y2) / 2 - 6} fill={palette.muted} fontSize="11" fontFamily={palette.font}>{line.name}</text>
          </g>
        )
      })}
      {optimum ? (
        <g>
          <circle cx={optimum[0]} cy={optimum[1]} r="4.5" fill={palette.ink} />
          <text x={optimum[0] + 8} y={optimum[1] - 8} fill={palette.ink} fontSize="12" fontFamily={palette.font}>opt</text>
        </g>
      ) : null}
      <text x={width / 2} y={height - 2} textAnchor="middle" fill={palette.muted} fontSize={palette.axisSize} fontFamily={palette.font}>{region.x}</text>
      <text x="14" y={height / 2} textAnchor="middle" fill={palette.muted} fontSize={palette.axisSize} fontFamily={palette.font} transform={`rotate(-90 14 ${height / 2})`}>{region.y}</text>
      {drag && cursor ? (
        <rect
          x={Math.min(drag.x, cursor.x)}
          y={Math.min(drag.y, cursor.y)}
          width={Math.abs(cursor.x - drag.x)}
          height={Math.abs(cursor.y - drag.y)}
          fill="rgba(61,79,99,0.12)"
          stroke={palette.bar}
        />
      ) : null}
    </svg>
    {readout ? <div className="fig-tip pointer-events-none absolute top-2 left-2">{readout}</div> : null}
    </div>
  )
}

function bounds(polygon: number[][]) {
  const xs = polygon.map((point) => point[0])
  const ys = polygon.map((point) => point[1])
  const padX = Math.max((Math.max(...xs) - Math.min(...xs)) * 0.12, 0.5)
  const padY = Math.max((Math.max(...ys) - Math.min(...ys)) * 0.12, 0.5)
  return { x0: Math.min(...xs) - padX, x1: Math.max(...xs) + padX, y0: Math.min(...ys) - padY, y1: Math.max(...ys) + padY }
}

function relative(node: SVGSVGElement, clientX: number, clientY: number) {
  const rect = node.getBoundingClientRect()
  const box = node.viewBox.baseVal
  return [((clientX - rect.left) / rect.width) * box.width, ((clientY - rect.top) / rect.height) * box.height]
}

function segmentDistance(px: number, py: number, x1: number, y1: number, x2: number, y2: number) {
  const dx = x2 - x1
  const dy = y2 - y1
  const length = dx * dx + dy * dy || 1
  const t = Math.max(0, Math.min(1, ((px - x1) * dx + (py - y1) * dy) / length))
  return Math.hypot(px - (x1 + t * dx), py - (y1 + t * dy))
}

function isoLines(polygon: number[][], x: number, y: number): number[][][] {
  const cx = polygon.reduce((sum, point) => sum + point[0], 0) / polygon.length
  const cy = polygon.reduce((sum, point) => sum + point[1], 0) / polygon.length
  const dx = x - cx
  const dy = y - cy
  const length = Math.hypot(dx, dy) || 1
  const nx = -dy / length
  const ny = dx / length
  return [0.35, 0.7, 1].map((scale) => {
    const ox = cx + dx * scale
    const oy = cy + dy * scale
    return [[ox - nx * length, oy - ny * length], [ox + nx * length, oy + ny * length]]
  })
}

function trim(value: number) {
  if (Math.abs(value) >= 100) return value.toFixed(0)
  if (Math.abs(value) >= 10) return value.toFixed(1)
  return value.toFixed(2)
}
