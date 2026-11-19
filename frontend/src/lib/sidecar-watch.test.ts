import assert from "node:assert/strict"
import test from "node:test"
import { foldHealth } from "./sidecar-watch.ts"

test("missed health checks ask for a restart, then a probe clears the banner", () => {
  const up = { misses: 0, phase: "up" as const }
  const once = foldHealth(up, "fail")
  assert.equal(once.phase, "up")
  assert.equal(once.restart, false)
  const twice = foldHealth(once, "fail")
  assert.equal(twice.phase, "restarting")
  assert.equal(twice.restart, false)
  const third = foldHealth(twice, "fail")
  assert.equal(third.phase, "down")
  assert.equal(third.restart, true)
  const held = foldHealth(third, "fail")
  assert.equal(held.restart, false)
  const recovered = foldHealth(third, "ok")
  assert.equal(recovered.phase, "up")
  assert.equal(recovered.misses, 0)
})
