import assert from "node:assert/strict"
import test from "node:test"
import { figureNumbers, latexFigure, scenarioCorrelation, slackHistogram, tornadoSeries } from "./figures.ts"

test("tornado bars split the objective swing around the base", () => {
  const rows = tornadoSeries([
    { name: "rhs:labor", low: 1500, base: 1628, high: 1800 },
    { name: "rhs:material", low: 1600, base: 1628, high: 1660 },
  ])
  assert.equal(rows[0].name, "rhs:labor")
  assert.ok(rows[0].down < 0 && rows[0].up > 0)
  assert.ok(Math.abs(rows[0].up - rows[0].down - rows[0].span) < 1e-6)
})

test("slack histogram counts every residual", () => {
  const bins = slackHistogram([0, 0, 1, 4], 2)
  assert.equal(bins.reduce((sum, bin) => sum + bin.count, 0), 4)
  assert.equal(bins.length, 2)
})

test("scenario correlation is one on the diagonal", () => {
  const matrix = scenarioCorrelation([
    { name: "a", variables: { x: 1, y: 2 } },
    { name: "b", variables: { x: 2, y: 3 } },
    { name: "c", variables: { x: 3, y: 5 } },
  ])
  assert.ok(matrix)
  assert.ok(Math.abs(matrix.matrix[0][0] - 1) < 1e-9)
  assert.ok(matrix.matrix[0][1] > 0.9)
})

test("figure numbers skip hidden plates and the latex snippet is a figure environment", () => {
  assert.deepEqual(figureNumbers([true, false, true]), [1, 0, 2])
  const latex = latexFigure("tornado", "Span of the objective, 100%")
  assert.match(latex, /\\begin\{figure\}/)
  assert.match(latex, /\\caption\{Span of the objective, 100\\%\}/)
  assert.match(latex, /\\label\{fig:tornado\}/)
})
