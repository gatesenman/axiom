export function progressPercent(done: number, total: number) {
  if (!Number.isFinite(done) || !Number.isFinite(total) || total <= 0) return 0
  return Math.max(0, Math.min(100, Math.round((100 * done) / total)))
}

export function stepGap(currentIso: string, previousIso?: string) {
  if (!previousIso) return ""
  const ms = Date.parse(currentIso) - Date.parse(previousIso)
  if (!Number.isFinite(ms) || ms < 500) return ""
  const sec = Math.round(ms / 1000)
  if (sec < 60) return `${sec}s`
  return `${Math.floor(sec / 60)}m ${sec % 60}s`
}

export function recommendation(input: {
  solver?: string
  objective?: number | null
  verification?: string
  top?: { name: string; value: number }[]
}, zh: boolean) {
  const solver = input.solver || (zh ? "求解器" : "Solver")
  const objective = input.objective == null || Number.isNaN(Number(input.objective)) ? "—" : String(input.objective)
  const lead = (input.top || []).slice(0, 2).map((item) => `${item.name} = ${item.value}`).join(zh ? "，" : ", ")
  const check = input.verification ? (zh ? `。${input.verification}` : `. ${input.verification}`) : ""
  if (zh) return `${solver} 给出目标 ${objective}${lead ? `。建议取值 ${lead}` : ""}${check}`
  return `${solver} reports objective ${objective}${lead ? `. Set ${lead}` : ""}${check}`
}

export function executiveSummary(input: {
  title?: string
  solver?: string
  status?: string
  objective?: number | null
  variables?: Record<string, number> | { name: string; value: number }[]
  constraints?: { name?: string; binding?: boolean }[]
}, zh: boolean) {
  const title = (input.title || "").trim() || (zh ? "这个模型" : "This model")
  const solver = input.solver || (zh ? "求解器" : "the solver")
  const status = _statusWord(input.status || "", zh)
  const objective = input.objective == null || Number.isNaN(Number(input.objective)) ? "—" : String(input.objective)
  const ranked = _ranked(input.variables).slice(0, 3)
  const lead = ranked.map((item) => `${item.name} = ${item.value}`).join(zh ? "，" : ", ")
  const binding = (input.constraints || []).filter((row) => row.binding && row.name).slice(0, 3).map((row) => row.name)
  const bounds = binding.join(zh ? "、" : ", ")
  if (zh) {
    const values = lead ? `主要取值是 ${lead}。` : ""
    const tight = bounds ? `${bounds} 达到边界。` : ""
    return `${title}已由 ${solver} 解出，状态为${status}。目标值是 ${objective}。${values}${tight}`.trim()
  }
  const values = lead ? ` The main values are ${lead}.` : ""
  const tight = bounds ? ` ${bounds} are binding.` : ""
  return `${title} was solved by ${solver} with status ${status}. The objective is ${objective}.${values}${tight}`.trim()
}

function _statusWord(status: string, zh: boolean) {
  const table: Record<string, [string, string]> = {
    optimal: ["最优", "optimal"],
    feasible: ["可行", "feasible"],
    infeasible: ["不可行", "infeasible"],
    completed: ["完成", "completed"],
  }
  const pair = table[status]
  if (!pair) return status || (zh ? "未知" : "unknown")
  return zh ? pair[0] : pair[1]
}

function _ranked(variables: Record<string, number> | { name: string; value: number }[] | undefined) {
  const rows = Array.isArray(variables)
    ? variables
    : Object.entries(variables || {}).map(([name, value]) => ({ name, value: Number(value) }))
  return rows
    .filter((row) => Number.isFinite(row.value))
    .sort((a, b) => Math.abs(b.value) - Math.abs(a.value))
}

export async function copyText(value: string) {
  try {
    await navigator.clipboard.writeText(value)
    return
  } catch {
    const area = document.createElement("textarea")
    area.value = value
    area.setAttribute("readonly", "")
    document.body.appendChild(area)
    area.select()
    document.execCommand("copy")
    area.remove()
  }
}
