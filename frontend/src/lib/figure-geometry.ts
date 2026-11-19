/** Geometry used by the figure plates: fronts, profiles, densities, decimation. */

export type XY = { x: number; y: number }

export function paretoMask(points: XY[], minimize = true): boolean[] {
  return points.map((point, index) => !points.some((other, otherIndex) => otherIndex !== index && dominates(other, point, minimize)))
}

export function paretoFront<T extends XY>(points: T[], minimize = true): T[] {
  const mask = paretoMask(points, minimize)
  return points.filter((_, index) => mask[index]).sort((a, b) => a.x - b.x)
}

export function kneePoint<T extends XY>(front: T[]): T | null {
  if (!front.length) return null
  const sorted = [...front].sort((a, b) => a.x - b.x)
  if (sorted.length < 3) return sorted[Math.floor((sorted.length - 1) / 2)]
  const start = sorted[0]
  const end = sorted[sorted.length - 1]
  const dx = end.x - start.x
  const dy = end.y - start.y
  const length = Math.hypot(dx, dy) || 1
  let best = sorted[0]
  let score = -1
  for (const point of sorted) {
    const distance = Math.abs(dy * point.x - dx * point.y + end.x * start.y - end.y * start.x) / length
    if (distance > score) {
      score = distance
      best = point
    }
  }
  return best
}

/** 2D hypervolume for a minimization front against a reference that is worse in both axes. */
export function hypervolume2d(front: XY[], ref: XY): number {
  const sorted = paretoFront(front, true).filter((point) => point.x < ref.x && point.y < ref.y)
  let volume = 0
  for (let index = 0; index < sorted.length; index += 1) {
    const nextX = index + 1 < sorted.length ? sorted[index + 1].x : ref.x
    volume += Math.max(0, nextX - sorted[index].x) * Math.max(0, ref.y - sorted[index].y)
  }
  return volume
}

export function kde(values: number[], samples = 64): XY[] {
  const nums = values.filter((value) => Number.isFinite(value))
  if (!nums.length) return []
  const mean = nums.reduce((sum, value) => sum + value, 0) / nums.length
  const variance = nums.reduce((sum, value) => sum + (value - mean) ** 2, 0) / Math.max(1, nums.length - 1)
  const sigma = Math.sqrt(variance) || 1
  const bandwidth = 1.06 * sigma * nums.length ** -0.2
  const lo = Math.min(...nums) - 3 * bandwidth
  const hi = Math.max(...nums) + 3 * bandwidth
  return Array.from({ length: samples }, (_, index) => {
    const x = lo + ((hi - lo) * index) / Math.max(1, samples - 1)
    const density = nums.reduce((sum, value) => sum + Math.exp(-0.5 * ((x - value) / bandwidth) ** 2), 0) / (nums.length * bandwidth * Math.sqrt(2 * Math.PI))
    return { x, y: density }
  })
}

export function ecdf(values: number[]): XY[] {
  const sorted = values.filter((value) => Number.isFinite(value)).sort((a, b) => a - b)
  return sorted.map((value, index) => ({ x: value, y: (index + 1) / sorted.length }))
}

export function percentiles(values: number[], ps = [0.05, 0.25, 0.5, 0.75, 0.95]): number[] {
  const sorted = values.filter((value) => Number.isFinite(value)).sort((a, b) => a - b)
  if (!sorted.length) return ps.map(() => Number.NaN)
  return ps.map((p) => {
    const rank = (sorted.length - 1) * p
    const lo = Math.floor(rank)
    const hi = Math.min(sorted.length - 1, lo + 1)
    return sorted[lo] + (sorted[hi] - sorted[lo]) * (rank - lo)
  })
}

export function boxStats(values: number[]) {
  const [p05, q1, mid, q3, p95] = percentiles(values)
  return { p05, q1, mid, q3, p95, min: Math.min(...values), max: Math.max(...values) }
}

export type ProfileRecord = { solver: string; problem: string; time: number }

export function performanceProfile(records: ProfileRecord[], steps = 24) {
  const problems = [...new Set(records.map((row) => row.problem))]
  const solvers = [...new Set(records.map((row) => row.solver))]
  const best = new Map<string, number>()
  for (const problem of problems) {
    const times = records.filter((row) => row.problem === problem && row.time > 0).map((row) => row.time)
    if (times.length) best.set(problem, Math.min(...times))
  }
  const ratios = new Map<string, number[]>()
  for (const solver of solvers) {
    ratios.set(solver, problems.map((problem) => {
      const row = records.find((item) => item.solver === solver && item.problem === problem)
      const base = best.get(problem)
      if (!row || !(row.time > 0) || !base) return Number.POSITIVE_INFINITY
      return row.time / base
    }))
  }
  const finite = [...ratios.values()].flat().filter((value) => Number.isFinite(value))
  const tauMax = Math.max(1.01, ...finite)
  const taus = Array.from({ length: steps }, (_, index) => 1 + ((tauMax - 1) * index) / Math.max(1, steps - 1))
  return solvers.map((solver) => ({
    solver,
    curve: taus.map((tau) => ({
      tau,
      rho: (ratios.get(solver) || []).filter((ratio) => ratio <= tau + 1e-9).length / Math.max(1, problems.length),
    })),
  }))
}

export function decimate(points: XY[], buckets: number): XY[] {
  if (points.length <= buckets * 2 || buckets < 1) return points
  const xs = points.map((point) => point.x)
  const lo = Math.min(...xs)
  const hi = Math.max(...xs)
  const width = (hi - lo) / buckets || 1
  const kept: XY[] = []
  for (let index = 0; index < buckets; index += 1) {
    const start = lo + index * width
    const end = index === buckets - 1 ? hi + 1e-9 : start + width
    const bin = points.filter((point) => point.x >= start && point.x < end)
    if (!bin.length) continue
    kept.push(bin.reduce((best, point) => (point.y < best.y ? point : best)))
    const high = bin.reduce((best, point) => (point.y > best.y ? point : best))
    if (high !== kept[kept.length - 1]) kept.push(high)
  }
  return kept
}

/** Average-linkage order of matrix rows. Returns the leaf order. */
export function clusterOrder(matrix: number[][]): number[] {
  const n = matrix.length
  if (n <= 2) return matrix.map((_, index) => index)
  let clusters = matrix.map((_, index) => [index])
  const distance = (left: number[], right: number[]) => {
    let sum = 0
    for (const a of left) for (const b of right) sum += rowDistance(matrix[a], matrix[b])
    return sum / (left.length * right.length)
  }
  while (clusters.length > 1) {
    let bestI = 0
    let bestJ = 1
    let best = Number.POSITIVE_INFINITY
    for (let i = 0; i < clusters.length; i += 1) {
      for (let j = i + 1; j < clusters.length; j += 1) {
        const value = distance(clusters[i], clusters[j])
        if (value < best) {
          best = value
          bestI = i
          bestJ = j
        }
      }
    }
    const merged = [...clusters[bestI], ...clusters[bestJ]]
    clusters = clusters.filter((_, index) => index !== bestI && index !== bestJ)
    clusters.push(merged)
  }
  return clusters[0]
}

export function morrisGuides(rows: { mu: number; sigma: number }[]) {
  const mu = median(rows.map((row) => row.mu))
  const sigma = median(rows.map((row) => row.sigma))
  return { mu, sigma }
}

export function contourBands(grid: number[][], levels = 6): number[] {
  const flat = grid.flat().filter((value) => Number.isFinite(value))
  if (!flat.length) return []
  const lo = Math.min(...flat)
  const hi = Math.max(...flat)
  if (hi === lo) return [lo]
  return Array.from({ length: levels }, (_, index) => lo + ((hi - lo) * (index + 1)) / (levels + 1))
}

export function matplotlibScript(title: string, rows: Array<Record<string, string | number | null | undefined>>): string {
  const headers = rows[0] ? Object.keys(rows[0]) : []
  const body = JSON.stringify(rows, null, 2)
  return [
    "import json",
    "import matplotlib.pyplot as plt",
    `rows = json.loads(${JSON.stringify(body)})`,
    `headers = ${JSON.stringify(headers)}`,
    "fig, ax = plt.subplots(figsize=(3.5, 2.6), layout='constrained')",
    "numeric = [key for key in headers if rows and isinstance(rows[0].get(key), (int, float))]",
    "if len(numeric) >= 2:",
    "    ax.plot([row[numeric[0]] for row in rows], [row[numeric[1]] for row in rows], color='#0072B2', lw=1.2)",
    "    ax.set_xlabel(numeric[0]); ax.set_ylabel(numeric[1])",
    "elif len(numeric) == 1:",
    "    ax.bar(range(len(rows)), [row[numeric[0]] for row in rows], color='#0072B2', width=0.72)",
    "    ax.set_ylabel(numeric[0])",
    `ax.set_title(${JSON.stringify(title)})`,
    "ax.grid(True, lw=0.4, color='#d9d3c7')",
    "fig.savefig('figure.pdf')",
    "",
  ].join("\n")
}

export function tikzSnippet(title: string, rows: Array<Record<string, string | number | null | undefined>>): string {
  const headers = rows[0] ? Object.keys(rows[0]) : []
  const numeric = headers.filter((key) => rows.some((row) => typeof row[key] === "number"))
  const xKey = numeric[0]
  const yKey = numeric[1] || numeric[0]
  const coords = rows
    .map((row, index) => {
      const x = typeof row[xKey] === "number" ? row[xKey] : index
      const y = typeof row[yKey] === "number" ? row[yKey] : 0
      return `(${x},${y})`
    })
    .join(" ")
  return [
    "% Requires pgfplots",
    "\\begin{tikzpicture}",
    "\\begin{axis}[",
    `  title={${escapeTex(title)}},`,
    `  xlabel={${escapeTex(xKey || "x")}},`,
    `  ylabel={${escapeTex(yKey || "y")}},`,
    "  grid=both,",
    "  minor tick num=3,",
    "  width=7.16cm",
    "]",
    `\\addplot+[mark=*] coordinates {${coords}};`,
    "\\end{axis}",
    "\\end{tikzpicture}",
  ].join("\n")
}

export function epsFromSeries(title: string, points: XY[]): string {
  const series = points.length ? points : [{ x: 0, y: 0 }, { x: 1, y: 1 }]
  const width = 360
  const height = 240
  const pad = 36
  const xs = series.map((point) => point.x)
  const ys = series.map((point) => point.y)
  const x0 = Math.min(...xs, 0)
  const x1 = Math.max(...xs, 1)
  const y0 = Math.min(...ys, 0)
  const y1 = Math.max(...ys, 1)
  const map = (point: XY) => {
    const x = pad + ((point.x - x0) / (x1 - x0 || 1)) * (width - pad * 2)
    const y = pad + ((point.y - y0) / (y1 - y0 || 1)) * (height - pad * 2)
    return `${x.toFixed(2)} ${y.toFixed(2)}`
  }
  const path = series.map((point, index) => `${map(point)} ${index === 0 ? "moveto" : "lineto"}`).join("\n")
  return [
    "%!PS-Adobe-3.0 EPSF-3.0",
    `%%BoundingBox: 0 0 ${width} ${height}`,
    `%%Title: ${title.replace(/[()\\]/g, " ")}`,
    "%%EOF is written at the end",
    "0.95 0.94 0.91 setrgbcolor",
    `0 0 ${width} ${height} rectfill`,
    "0.85 0.82 0.76 setrgbcolor 0.4 setlinewidth",
    `${pad} ${pad} moveto ${width - pad} ${pad} lineto stroke`,
    `${pad} ${pad} moveto ${pad} ${height - pad} lineto stroke`,
    "0 0.447 0.698 setrgbcolor 1.2 setlinewidth",
    path,
    "stroke",
    "0 0 0 setrgbcolor",
    "/Times-Roman findfont 9 scalefont setfont",
    `${pad} ${height - 16} moveto (${title.replace(/[()\\]/g, " ")}) show`,
    "%%EOF",
    "",
  ].join("\n")
}

function dominates(left: XY, right: XY, minimize: boolean) {
  const better = (a: number, b: number) => (minimize ? a <= b : a >= b)
  const strict = (a: number, b: number) => (minimize ? a < b : a > b)
  return better(left.x, right.x) && better(left.y, right.y) && (strict(left.x, right.x) || strict(left.y, right.y))
}

function rowDistance(left: number[], right: number[]) {
  const n = Math.min(left.length, right.length)
  let sum = 0
  for (let index = 0; index < n; index += 1) sum += (left[index] - right[index]) ** 2
  return Math.sqrt(sum)
}

function median(values: number[]) {
  const sorted = [...values].sort((a, b) => a - b)
  if (!sorted.length) return 0
  const mid = Math.floor(sorted.length / 2)
  return sorted.length % 2 ? sorted[mid] : (sorted[mid - 1] + sorted[mid]) / 2
}

function escapeTex(value: string) {
  return value.replaceAll("\\", "\\textbackslash ").replaceAll("&", "\\&").replaceAll("%", "\\%").replaceAll("_", "\\_")
}
