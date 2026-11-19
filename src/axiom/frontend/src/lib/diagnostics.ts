export type AmlDiagnostic = {
  level: string
  message: string
  message_en?: string
  line?: number
  code?: string
}

/** Map a validator line onto a real document line. Missing lines land on line 1. */
export function clampLine(line: number | undefined, lineCount: number) {
  const count = Math.max(1, lineCount || 1)
  const raw = Number(line)
  if (!Number.isFinite(raw) || raw < 1) return 1
  return Math.min(Math.floor(raw), count)
}

export function diagnosticLabel(item: AmlDiagnostic, zh: boolean) {
  const text = zh ? item.message : item.message_en || item.message
  const line = item.line && item.line > 0 ? item.line : 1
  return { line, text }
}
