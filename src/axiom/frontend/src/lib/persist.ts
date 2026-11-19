export type StorageLike = {
  length: number
  key(index: number): string | null
  getItem(key: string): string | null
  setItem(key: string, value: string): void
  removeItem(key: string): void
}

const PORT_KEYS = /api[-_]?base|base[-_]?url|sidecar|^axiom[._]port$|^port$/i
const LOOPBACK = /^https?:\/\/(127\.0\.0\.1|localhost)(:\d+)?\/?$/i
const ENUMS: Record<string, string[]> = {
  axiom_locale: ["zh-CN", "en"],
  axiom_motion: ["reduce", "full"],
  theme: ["light", "dark", "system"],
  "axiom.tour": ["done"],
  "axiom.notify": ["0", "1"],
  "axiom.sound": ["0", "1"],
  "axiom.tip.conclusion": ["off"],
}

export function canPersist(key: string, value: string) {
  if (PORT_KEYS.test(key)) return false
  const text = String(value ?? "")
  if (LOOPBACK.test(text.trim())) return false
  if (/127\.0\.0\.1:\d+|localhost:\d+/.test(text) && /apiBase|"port"/.test(text)) return false
  return true
}

function acceptableToken(value: string) {
  return /^[A-Za-z0-9._~+/-]{16,512}$/.test(value)
}

function acceptableJson(raw: string, check: (parsed: unknown) => boolean) {
  try {
    const parsed = JSON.parse(raw) as unknown
    if (/127\.0\.0\.1:\d+|localhost:\d+/.test(raw) && /apiBase|"port"/.test(raw)) return false
    return check(parsed)
  } catch {
    return false
  }
}

export function migratePersistedState(storage: StorageLike) {
  const removed: string[] = []
  const keys: string[] = []
  for (let index = 0; index < storage.length; index += 1) {
    const key = storage.key(index)
    if (key) keys.push(key)
  }
  for (const key of keys) {
    const value = storage.getItem(key)
    if (value == null) continue
    let drop = false
    if (!canPersist(key, value)) drop = true
    else if (key === "axiom_token") drop = !acceptableToken(value)
    else if (key === "axiom.layout") drop = !acceptableJson(value, (parsed) => Boolean(parsed) && typeof parsed === "object" && !Array.isArray(parsed))
    else if (key === "axiom.recovery") {
      drop = !acceptableJson(value, (parsed) => {
        if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) return false
        const draft = parsed as { projectId?: unknown; dsl?: unknown }
        return typeof draft.projectId === "number" && typeof draft.dsl === "string"
      })
    } else if (key in ENUMS) drop = !ENUMS[key].includes(value)
    if (!drop) continue
    storage.removeItem(key)
    removed.push(key)
  }
  return removed
}

export function storedLocale(storage: StorageLike) {
  migratePersistedState(storage)
  return storage.getItem("axiom_locale") === "en" ? "en" : "zh-CN"
}

let guardInstalled = false

export function installPersistGuard(storage: StorageLike) {
  if (guardInstalled) return
  const native = storage.setItem.bind(storage)
  storage.setItem = (key: string, value: string) => {
    if (!canPersist(key, String(value))) return
    native(key, String(value))
  }
  guardInstalled = true
}
