import assert from "node:assert/strict"
import test from "node:test"
import { compareSolutions } from "./compare.ts"

test("run comparison reports objective and variable deltas", () => {
  const diff = compareSolutions(
    { objective: "10", variables: { xA: 1, xB: 2 } },
    { objective: 14, variables: { xA: 3, xC: 1 } },
  )
  assert.equal(diff.objectiveDelta, 4)
  assert.deepEqual(
    diff.rows.map((row) => [row.name, row.delta]),
    [
      ["xA", 2],
      ["xB", null],
      ["xC", null],
    ],
  )
})
