export type SolutionSide = {
  objective?: number | string | null
  variables?: Record<string, number>
}

export type DiffRow = {
  name: string
  left: number | null
  right: number | null
  delta: number | null
}

export function compareSolutions(left: SolutionSide, right: SolutionSide) {
  const leftVars = left.variables || {}
  const rightVars = right.variables || {}
  const names = [...new Set([...Object.keys(leftVars), ...Object.keys(rightVars)])].filter((name) => !name.startsWith("_"))
  const rows: DiffRow[] = names.map((name) => {
    const before = typeof leftVars[name] === "number" ? leftVars[name] : null
    const after = typeof rightVars[name] === "number" ? rightVars[name] : null
    return { name, left: before, right: after, delta: before === null || after === null ? null : after - before }
  })
  const leftObj = numberOrNull(left.objective)
  const rightObj = numberOrNull(right.objective)
  return {
    objectiveLeft: leftObj,
    objectiveRight: rightObj,
    objectiveDelta: leftObj === null || rightObj === null ? null : rightObj - leftObj,
    rows,
  }
}

function numberOrNull(value: number | string | null | undefined) {
  if (value === null || value === undefined || value === "") return null
  const number = Number(value)
  return Number.isFinite(number) ? number : null
}
