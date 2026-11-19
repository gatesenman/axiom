export type LayoutPrefs = {
  leftWidth?: number
  rightWidth?: number
  bottomHeight?: number
  leftOpen?: boolean
  rightOpen?: boolean
  bottomOpen?: boolean
  doc?: string
  minimap?: boolean
  reducedMotion?: boolean
}

const KEY = "axiom.layout"

export function clampSize(value: unknown, fallback: number, min: number, max: number) {
  const number = Number(value)
  if (!Number.isFinite(number)) return fallback
  return Math.min(max, Math.max(min, Math.round(number)))
}

export function loadLayout(): LayoutPrefs {
  try {
    const raw = localStorage.getItem(KEY)
    if (!raw) return {}
    const parsed = JSON.parse(raw) as LayoutPrefs
    return parsed && typeof parsed === "object" ? parsed : {}
  } catch {
    return {}
  }
}

export function saveLayout(prefs: LayoutPrefs) {
  localStorage.setItem(KEY, JSON.stringify(prefs))
}
