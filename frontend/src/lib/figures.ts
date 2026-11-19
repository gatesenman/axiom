export type TornadoRow = { name: string; base: number; down: number; up: number; span: number }

export function tornadoSeries(rows: { name: string; low: number; high: number; base?: number; span?: number }[] | null | undefined): TornadoRow[] {
  if (!rows) return []
  return rows
    .map((row) => {
      const low = Number(row.low)
      const high = Number(row.high)
      const base = Number(row.base)
      const span = Number.isFinite(high - low) ? high - low : Number(row.span)
      const down = Number.isFinite(base) ? Math.min(0, low - base, high - base) : 0
      const up = Number.isFinite(base) ? Math.max(0, high - base, low - base) : 0
      return { name: row.name, base, down, up, span }
    })
    .filter((row) => Number.isFinite(row.span))
    .sort((a, b) => b.span - a.span)
}

export type HistBin = { name: string; count: number; lo: number; hi: number }

export function slackHistogram(values: number[] | null | undefined, bins = 6): HistBin[] {
  const nums = (values || []).map(Number).filter((value) => Number.isFinite(value))
  if (!nums.length) return []
  const count = Math.max(1, Math.min(bins, nums.length))
  const lo = Math.min(...nums)
  const hi = Math.max(...nums)
  const width = hi === lo ? 1 : (hi - lo) / count
  const built = Array.from({ length: count }, (_, index) => {
    const start = lo + index * width
    const end = index === count - 1 ? hi : start + width
    return { name: `${trim(start)}–${trim(end)}`, count: 0, lo: start, hi: end }
  })
  for (const value of nums) {
    let index = width === 0 ? 0 : Math.floor((value - lo) / width)
    if (index >= built.length) index = built.length - 1
    if (index < 0) index = 0
    built[index].count += 1
  }
  return built
}

export function scenarioCorrelation(rows: { name: string; variables?: Record<string, number> | null }[] | null | undefined) {
  const usable = (rows || []).filter((row) => row.variables && Object.keys(row.variables).length > 0)
  if (usable.length < 2) return null
  const names = Object.keys(usable[0].variables || {}).filter((name) => !name.startsWith("_") && !name.startsWith("s_") && usable.every((row) => typeof row.variables?.[name] === "number"))
  if (names.length < 2) return null
  const series = Object.fromEntries(names.map((name) => [name, usable.map((row) => Number(row.variables?.[name]))]))
  return {
    names,
    matrix: names.map((left) => names.map((right) => pearson(series[left], series[right]))),
  }
}

export function racePoints(rows: { solver: string; status: string; objective?: number | null; runtime_sec?: number }[] | null | undefined) {
  const points = []
  for (const row of rows || []) {
    const objective = Number(row.objective)
    if ((row.status !== "optimal" && row.status !== "feasible") || !Number.isFinite(objective)) continue
    points.push({ name: row.solver, objective, time: Number(row.runtime_sec) || 0 })
  }
  return points.sort((a, b) => a.time - b.time)
}

export function figureNumbers(flags: boolean[]) {
  let next = 0
  return flags.map((on) => (on ? ++next : 0))
}

export function latexFigure(label: string, caption: string) {
  const safe = caption.replaceAll("&", "\\&").replaceAll("%", "\\%")
  return [
    "\\begin{figure}[htbp]",
    "  \\centering",
    `  \\includegraphics[width=0.82\\linewidth]{fig-${label}.pdf}`,
    `  \\caption{${safe}}`,
    `  \\label{fig:${label}}`,
    "\\end{figure}",
  ].join("\n")
}

function pearson(left: number[], right: number[]) {
  const n = Math.min(left.length, right.length)
  if (n < 2) return 0
  const mean = (values: number[]) => values.reduce((sum, value) => sum + value, 0) / n
  const lx = mean(left)
  const ly = mean(right)
  let num = 0
  let dx = 0
  let dy = 0
  for (let index = 0; index < n; index += 1) {
    const a = left[index] - lx
    const b = right[index] - ly
    num += a * b
    dx += a * a
    dy += b * b
  }
  if (dx <= 1e-12 || dy <= 1e-12) return 0
  return num / Math.sqrt(dx * dy)
}

function trim(value: number) {
  if (Math.abs(value - Math.round(value)) < 1e-6) return String(Math.round(value))
  return value.toFixed(2)
}
