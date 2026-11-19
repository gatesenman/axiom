import assert from "node:assert/strict"
import test from "node:test"
import { clampLine, diagnosticLabel } from "./diagnostics.ts"
import { clampSize } from "./layout.ts"

test("panel sizes stay inside the splitter range", () => {
  assert.equal(clampSize(undefined, 248, 180, 460), 248)
  assert.equal(clampSize(10, 248, 180, 460), 180)
  assert.equal(clampSize(900, 248, 180, 460), 460)
  assert.equal(clampSize(220.4, 248, 180, 460), 220)
})

test("problem labels follow the active language", () => {
  const item = { level: "error", message: "集合为空", message_en: "Set is empty", line: 3 }
  assert.deepEqual(diagnosticLabel(item, true), { line: 3, text: "集合为空" })
  assert.deepEqual(diagnosticLabel(item, false), { line: 3, text: "Set is empty" })
  assert.equal(diagnosticLabel({ level: "error", message: "语法错误" }, false).line, 1)
})

test("diagnostic lines clamp onto the document", () => {
  assert.equal(clampLine(undefined, 12), 1)
  assert.equal(clampLine(0, 12), 1)
  assert.equal(clampLine(4, 12), 4)
  assert.equal(clampLine(40, 12), 12)
  assert.equal(clampLine(3, 0), 1)
})
