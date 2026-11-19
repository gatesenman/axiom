import assert from "node:assert/strict"
import test from "node:test"
import { historyPush, historyRedo, historyStart, historyUndo } from "./history.ts"

test("model history undoes and redoes dsl snapshots", () => {
  let state = historyStart("a")
  state = historyPush(state, "b")
  state = historyPush(state, "b")
  state = historyPush(state, "c")
  assert.equal(historyUndo(state).present, "b")
  assert.equal(historyRedo(historyUndo(state)).present, "c")
  assert.equal(historyUndo(historyStart("a")).present, "a")
})
