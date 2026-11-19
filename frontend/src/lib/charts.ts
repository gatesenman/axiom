/** Chart series shared by the results page and its tests. */

export type NamedValue = { name: string; value: number }

export type SensitivityInput = {
  name: string
  low: number
  high: number
  base?: number
  span?: number
}

export type ScenarioInput = { name: string; objective: number | null }

export type GanttInput = { id: string; start: number; duration: number; end?: number }

export type GanttBox = { id: string; left: number; width: number }

function hidden(name: string) {
  return name.startsWith("_") || name.startsWith("s_")
}

/** Decision variables in model order, the same order as the results table. */
export function variableBars(variables: Record<string, number> | null | undefined): NamedValue[] {
  if (!variables) return []
  const rows: NamedValue[] = []
  for (const [name, raw] of Object.entries(variables)) {
    const value = Number(raw)
    if (hidden(name) || !Number.isFinite(value)) continue
    rows.push({ name, value })
  }
  return rows
}

/** Bar length is the objective range (high − low), recomputed from the endpoints. */
export function sensitivitySeries<T extends SensitivityInput>(rows: T[] | null | undefined): (T & { span: number })[] {
  if (!rows) return []
  return rows.map((row) => {
    const low = Number(row.low)
    const high = Number(row.high)
    const span = Number.isFinite(high - low) ? high - low : Number(row.span)
    return { ...row, low, high, span }
  })
}

/** Scenario height is the scenario objective itself. */
export function scenarioSeries(rows: ScenarioInput[] | null | undefined): { name: string; objective: number }[] {
  if (!rows) return []
  const series: { name: string; objective: number }[] = []
  for (const row of rows) {
    const objective = Number(row.objective)
    if (row.objective === null || !Number.isFinite(objective)) continue
    series.push({ name: row.name, objective })
  }
  return series
}

/**
 * Place each job on a 0–100 track whose horizon is the latest finish.
 * A fixed percent-per-time-unit overflows once a start or duration exceeds that unit.
 */
export function ganttLayout(rows: GanttInput[] | null | undefined): GanttBox[] {
  if (!rows?.length) return []
  const finishes = rows.map((row) => {
    const start = Number(row.start) || 0
    const duration = Number(row.duration) || 0
    const end = Number.isFinite(Number(row.end)) ? Number(row.end) : start + duration
    return Math.max(end, start + duration, 0)
  })
  const horizon = Math.max(...finishes, 1e-9)
  return rows.map((row) => {
    const start = Math.max(Number(row.start) || 0, 0)
    const duration = Math.max(Number(row.duration) || 0, 0)
    const left = (start / horizon) * 100
    let width = (duration / horizon) * 100
    if (duration > 0) width = Math.max(width, 1.5)
    if (left + width > 100) width = Math.max(100 - left, 0)
    return { id: row.id, left, width }
  })
}
