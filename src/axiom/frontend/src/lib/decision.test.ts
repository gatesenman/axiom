import assert from "node:assert/strict"
import test from "node:test"
import { executiveSummary, progressPercent, recommendation, stepGap } from "./decision.ts"

test("solve progress stays inside 0 to 100", () => {
  assert.equal(progressPercent(0, 0), 0)
  assert.equal(progressPercent(1, 4), 25)
  assert.equal(progressPercent(4, 4), 100)
  assert.equal(progressPercent(9, 4), 100)
})

test("agent steps show a gap only when time actually passed", () => {
  assert.equal(stepGap("2026-10-16T12:00:02.000Z", "2026-10-16T12:00:00.000Z"), "2s")
  assert.equal(stepGap("2026-10-16T12:00:00.200Z", "2026-10-16T12:00:00.000Z"), "")
  assert.equal(stepGap("2026-10-16T12:00:00.000Z"), "")
})

test("the recommendation names the objective and the leading variables", () => {
  const text = recommendation({
    solver: "HiGHS",
    objective: 1628.5714285714287,
    verification: "可行",
    top: [{ name: "x_A", value: 21.4286 }, { name: "x_B", value: 25.7143 }],
  }, true)
  assert.match(text, /HiGHS/)
  assert.match(text, /1628\.5714285714287/)
  assert.match(text, /x_A = 21\.4286/)
  assert.match(text, /可行/)
})

test("the executive summary is one paragraph in the active language", () => {
  const zh = executiveSummary({
    title: "产品组合",
    solver: "HiGHS",
    status: "optimal",
    objective: 1628.57,
    variables: { xA: 21.43, xB: 25.71 },
    constraints: [{ name: "labor", binding: true }, { name: "material", binding: true }],
  }, true)
  assert.match(zh, /产品组合/)
  assert.match(zh, /最优/)
  assert.match(zh, /1628\.57/)
  assert.match(zh, /xA = 21\.43/)
  assert.match(zh, /labor/)
  const en = executiveSummary({
    title: "Product mix",
    solver: "HiGHS",
    status: "optimal",
    objective: 1628.57,
    variables: { xA: 21.43 },
  }, false)
  assert.match(en, /Product mix/)
  assert.match(en, /optimal/)
  assert.match(en, /objective is 1628\.57/)
})
