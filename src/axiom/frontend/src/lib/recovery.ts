export type Draft = {
  projectId: number
  title: string
  statement: string
  dsl: string
  auto: boolean
  solver: string
  algorithm?: string
  savedAt: string
}

export const RECOVERY_KEY = "axiom.recovery"

export function saveDraft(draft: Draft) {
  localStorage.setItem(RECOVERY_KEY, JSON.stringify(draft))
}

export function loadDraft(): Draft | null {
  try {
    const raw = localStorage.getItem(RECOVERY_KEY)
    if (!raw) return null
    const parsed = JSON.parse(raw) as Draft
    if (!parsed || typeof parsed.projectId !== "number" || typeof parsed.dsl !== "string") return null
    return parsed
  } catch {
    return null
  }
}

export function clearDraft() {
  localStorage.removeItem(RECOVERY_KEY)
}

export function draftDiffers(draft: Draft, saved: { projectId: number; title: string; statement: string; dsl: string }) {
  if (draft.projectId !== saved.projectId) return false
  return draft.title !== saved.title || draft.statement !== saved.statement || draft.dsl !== saved.dsl
}
