const assert = require("node:assert/strict")
const test = require("node:test")
const { placeWindow } = require("./window-state.cjs")

const fallback = { width: 1440, height: 920 }

test("a 1440x920 window is clamped into a 150% 2133x1333 work area", () => {
  const displays = [{ primary: true, scaleFactor: 1.5, workArea: { x: 0, y: 0, width: 1422, height: 889 } }]
  const placed = placeWindow({ x: 0, y: 0, width: 1440, height: 920 }, displays, fallback)
  assert.equal(placed.reason, "ok")
  assert.ok(placed.width <= 1422)
  assert.ok(placed.height <= 889)
  assert.ok(placed.x >= 0)
  assert.ok(placed.y >= 0)
  assert.ok(placed.x + placed.width <= 1422)
  assert.ok(placed.y + placed.height <= 889)
})

test("offscreen saved bounds are replaced with a centered window", () => {
  const displays = [{ primary: true, scaleFactor: 1.5, workArea: { x: 0, y: 0, width: 1422, height: 889 } }]
  const placed = placeWindow({ x: -4000, y: 40, width: 1440, height: 920, minimized: true }, displays, fallback)
  assert.equal(placed.reason, "offscreen")
  assert.equal(placed.maximized, false)
  assert.ok(placed.x >= 0 && placed.y >= 0)
  assert.ok(placed.x + placed.width <= 1422)
  assert.ok(placed.y + placed.height <= 889)
})

test("on-screen bounds are kept and a minimized window is restored", () => {
  const displays = [{ primary: true, scaleFactor: 1, workArea: { x: 0, y: 0, width: 1920, height: 1080 } }]
  const placed = placeWindow({ x: 80, y: 60, width: 1280, height: 800, minimized: true, maximized: true }, displays, fallback)
  assert.equal(placed.reason, "restored")
  assert.equal(placed.x, 80)
  assert.equal(placed.y, 60)
  assert.equal(placed.width, 1280)
  assert.equal(placed.height, 800)
  assert.equal(placed.maximized, false)
})

test("a maximized window stays maximized only when its bounds are on screen", () => {
  const displays = [{ primary: true, scaleFactor: 1, workArea: { x: 0, y: 0, width: 1920, height: 1080 } }]
  const placed = placeWindow({ x: 0, y: 0, width: 1920, height: 1080, maximized: true }, displays, fallback)
  assert.equal(placed.maximized, true)
  assert.equal(placed.reason, "ok")
})
