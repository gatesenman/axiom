import assert from "node:assert/strict"
import test from "node:test"
import { decimate, ecdf, hypervolume2d, kde, kneePoint, matplotlibScript, paretoFront, performanceProfile, tikzSnippet } from "./figure-geometry.ts"

test("pareto front drops dominated points and the knee is the middle tradeoff", () => {
  const points = [
    { x: 1, y: 4 },
    { x: 2, y: 2 },
    { x: 4, y: 1 },
    { x: 3, y: 3 },
  ]
  const front = paretoFront(points)
  assert.deepEqual(front.map((point) => point.x), [1, 2, 4])
  assert.equal(kneePoint(front)?.x, 2)
  const volume = hypervolume2d(front, { x: 5, y: 5 })
  assert.ok(volume > 0)
  assert.ok(volume < 25)
})

test("kde and ecdf cover the sample", () => {
  const density = kde([1, 2, 2, 3], 16)
  assert.equal(density.length, 16)
  assert.ok(Math.max(...density.map((point) => point.y)) > 0)
  const cdf = ecdf([1, 2, 3])
  assert.equal(cdf.at(-1)?.y, 1)
})

test("Dolan-Moré profile reaches one and ranks the faster solver first", () => {
  const curves = performanceProfile([
    { solver: "highs", problem: "mix", time: 1 },
    { solver: "scip", problem: "mix", time: 2 },
    { solver: "highs", problem: "diet", time: 2 },
    { solver: "scip", problem: "diet", time: 2 },
  ])
  const highs = curves.find((curve) => curve.solver === "highs")
  const scip = curves.find((curve) => curve.solver === "scip")
  assert.equal(highs?.curve[0].rho, 1)
  assert.equal(scip?.curve[0].rho, 0.5)
  assert.equal(highs?.curve.at(-1)?.rho, 1)
  assert.equal(scip?.curve.at(-1)?.rho, 1)
})

test("decimation of 100k points keeps both extrema", () => {
  const points = Array.from({ length: 100_000 }, (_, index) => ({ x: index, y: Math.sin(index / 80) + (index === 20 ? 5 : 0) + (index === 90_000 ? -4 : 0) }))
  const small = decimate(points, 400)
  assert.ok(small.length <= 800)
  assert.ok(small.length > 100)
  assert.ok(small.some((point) => point.y === 5 + Math.sin(20 / 80)))
  assert.ok(small.some((point) => point.x === 90_000))
})

test("matplotlib and tikz snippets contain the plotted numbers", () => {
  const rows = [{ x: 1, y: 2 }, { x: 2, y: 3 }]
  assert.match(matplotlibScript("产品组合", rows), /matplotlib/)
  assert.match(matplotlibScript("产品组合", rows), /产品组合/)
  const tikz = tikzSnippet("mix", rows)
  assert.match(tikz, /pgfplots|tikzpicture/)
  assert.match(tikz, /\(1,2\)/)
})
