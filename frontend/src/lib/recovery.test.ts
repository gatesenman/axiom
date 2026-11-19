import assert from "node:assert/strict"
import test from "node:test"
import { draftDiffers, type Draft } from "./recovery.ts"

const draft: Draft = {
  projectId: 4,
  title: "产品组合",
  statement: "改过",
  dsl: "subject to labor: x <= 100;",
  auto: false,
  solver: "highs",
  savedAt: "2026-10-16T00:00:00.000Z",
}

test("a crash draft is offered only when it differs from the saved project", () => {
  assert.equal(draftDiffers(draft, { projectId: 4, title: "产品组合", statement: "改过", dsl: "subject to labor: x <= 100;" }), false)
  assert.equal(draftDiffers(draft, { projectId: 4, title: "产品组合", statement: "原文", dsl: "subject to labor: x <= 120;" }), true)
  assert.equal(draftDiffers(draft, { projectId: 9, title: "产品组合", statement: "改过", dsl: "other" }), false)
})
