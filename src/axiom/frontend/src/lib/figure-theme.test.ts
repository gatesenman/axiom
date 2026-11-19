import assert from "node:assert/strict"
import test from "node:test"
import { colormap, divergingRdBu, formatSI, themeFor } from "./figure-theme.ts"

test("themes keep a journal column width and a distinct serif for publication", () => {
  const pub = themeFor("publication")
  const dark = themeFor("screen-dark")
  assert.equal(pub.columnIn.one, 3.5)
  assert.equal(pub.columnIn.two, 7.16)
  assert.match(pub.font, /Liberation Serif/)
  assert.match(dark.font, /Source Sans 3/)
  assert.notEqual(pub.bg, dark.bg)
  assert.equal(pub.categorical.length >= 8, true)
})

test("viridis and RdBu are deterministic and stay in range", () => {
  assert.equal(colormap("viridis", 0), colormap("viridis", 0))
  assert.notEqual(colormap("viridis", 0), colormap("viridis", 1))
  assert.match(colormap("cividis", 0.5), /^rgb\(/)
  assert.match(divergingRdBu(0), /^rgb\(/)
  assert.notEqual(divergingRdBu(-1), divergingRdBu(1))
})

test("SI formatting uses a thin space and a prefix", () => {
  assert.equal(formatSI(1628.57, "元"), "1.63\u202fk元")
  assert.equal(formatSI(0.0042, "m"), "4.2\u202fmm")
  assert.equal(formatSI(-12, "s"), "−12\u202fs")
  assert.equal(formatSI(Number.NaN, "s"), "—")
})
