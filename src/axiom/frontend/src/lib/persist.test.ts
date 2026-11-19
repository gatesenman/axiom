import assert from "node:assert/strict"
import test from "node:test"
import { canPersist, installPersistGuard, migratePersistedState, storedLocale, type StorageLike } from "./persist.ts"

class MemoryStorage implements StorageLike {
  private values = new Map<string, string>()

  get length() {
    return this.values.size
  }

  key(index: number) {
    return [...this.values.keys()][index] ?? null
  }

  getItem(key: string) {
    return this.values.has(key) ? this.values.get(key)! : null
  }

  setItem(key: string, value: string) {
    this.values.set(key, String(value))
  }

  removeItem(key: string) {
    this.values.delete(key)
  }
}

test("stale loopback bases and ports are dropped and never written back", () => {
  const storage = new MemoryStorage()
  storage.setItem("axiom.apiBase", "http://127.0.0.1:43124")
  storage.setItem("axiom_port", "43124")
  storage.setItem("legacy", "http://localhost:43124")
  storage.setItem("axiom.layout", JSON.stringify({ leftWidth: 280, apiBase: "http://127.0.0.1:43124" }))
  storage.setItem("axiom_token", "not a token")
  storage.setItem("axiom_locale", "zh")
  storage.setItem("axiom.recovery", "{")
  storage.setItem("theme", "dark")
  const removed = migratePersistedState(storage)
  assert.ok(removed.includes("axiom.apiBase"))
  assert.ok(removed.includes("axiom_port"))
  assert.ok(removed.includes("legacy"))
  assert.ok(removed.includes("axiom.layout"))
  assert.ok(removed.includes("axiom_token"))
  assert.ok(removed.includes("axiom_locale"))
  assert.ok(removed.includes("axiom.recovery"))
  assert.equal(storage.getItem("theme"), "dark")
  assert.equal(storedLocale(storage), "zh-CN")
  installPersistGuard(storage)
  storage.setItem("axiom.apiBase", "http://127.0.0.1:60221")
  storage.setItem("axiom_token", "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa")
  assert.equal(storage.getItem("axiom.apiBase"), null)
  assert.equal(storage.getItem("axiom_token"), "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa")
  assert.equal(canPersist("note", "localhost:43124 is mentioned beside apiBase"), false)
})

test("a valid draft and locale survive migration", () => {
  const storage = new MemoryStorage()
  storage.setItem("axiom_locale", "en")
  storage.setItem("axiom.recovery", JSON.stringify({ projectId: 4, title: "mix", statement: "", dsl: "max: x;", auto: true, solver: "highs", savedAt: "2026-10-10T00:00:00Z" }))
  storage.setItem("axiom_token", "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa")
  assert.deepEqual(migratePersistedState(storage), [])
  assert.equal(storedLocale(storage), "en")
  assert.equal(storage.getItem("axiom_token")?.length, 43)
})
