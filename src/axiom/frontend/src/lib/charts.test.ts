import assert from "node:assert/strict"
import { test } from "node:test"

import { ganttLayout, scenarioSeries, sensitivitySeries, variableBars } from "./charts.ts"

test("variable bars keep table order and values", () => {
  const bars = variableBars({ x_A: 150 / 7, x_B: 180 / 7, _aux: 9, s_labor: 4 })
  assert.deepEqual(
    bars.map((row) => row.name),
    ["x_A", "x_B"],
  )
  assert.ok(Math.abs(bars[0].value - 21.428571) < 1e-4)
  assert.ok(Math.abs(bars[1].value - 25.714286) < 1e-4)
  assert.ok(bars[1].value / bars[0].value > 1.15)
})

test("scenario series keeps the objective, including values above 1000", () => {
  const rows = scenarioSeries([
    { name: "基准", objective: 1628.571 },
    { name: "右端 +10%", objective: 1791.429 },
    { name: "右端 -10%", objective: 1465.714 },
  ])
  assert.equal(rows.length, 3)
  assert.ok(rows.every((row) => row.objective > 1000))
  assert.ok(rows[1].objective > rows[0].objective && rows[0].objective > rows[2].objective)
})

test("sensitivity span is high minus low, a range rather than the objective", () => {
  const rows = sensitivitySeries([
    { name: "rhs:labor", low: 1540, base: 1628.57, high: 1711, span: 1628.57 },
  ])
  assert.ok(Math.abs(rows[0].span - (1711 - 1540)) < 1e-6)
  assert.ok(rows[0].span < rows[0].base)
})

test("gantt boxes stay inside the track when times exceed a fixed percent scale", () => {
  const boxes = ganttLayout([
    { id: "J1", start: 0, duration: 3, end: 3 },
    { id: "J2", start: 10, duration: 2, end: 12 },
    { id: "J3", start: 20, duration: 4, end: 24 },
  ])
  assert.equal(boxes.map((row) => row.id).join(","), "J1,J2,J3")
  for (const box of boxes) {
    assert.ok(box.left >= 0 && box.width >= 0)
    assert.ok(box.left + box.width <= 100.001)
  }
  assert.ok(boxes[2].left > boxes[1].left && boxes[1].left > boxes[0].left)
  assert.ok(boxes[2].left > 80)
})
