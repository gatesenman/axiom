export type LoginFailureKind = "password" | "sidecar" | "api"

type ErrorLike = {
  name?: string
  message?: string
  messageEn?: string
  status?: number
}

function asError(error: unknown): ErrorLike {
  if (!error || typeof error !== "object") return {}
  return error as ErrorLike
}

export function classifyLoginError(error: unknown): LoginFailureKind {
  const body = asError(error)
  const status = Number(body.status || 0)
  if (body.name === "ApiError" && (status === 401 || status === 403)) return "password"
  if (body.name === "ApiError" && status >= 400) return "api"
  return "sidecar"
}

export function sidecarDownText(detail: string, zh: boolean) {
  const extra = detail.trim()
  if (zh) {
    const tail = extra ? ` ${extra}` : ""
    return `求解服务没有响应，侧车可能已经退出。${tail} 请等待自动重连，或退出公理后重新打开。`
  }
  const tail = extra ? ` ${extra}` : ""
  return `The solver service is not responding. The sidecar may have exited.${tail} Wait for the automatic restart, or quit Axiom and relaunch.`
}

export function loginToast(error: unknown, zh: boolean, fallback: string) {
  const kind = classifyLoginError(error)
  const body = asError(error)
  if (kind === "password" || kind === "api") {
    const text = (zh ? body.message : body.messageEn || body.message) || fallback
    return { kind, text }
  }
  const raw = body.message || ""
  if (/求解服务没有响应|solver service is not responding/i.test(raw)) return { kind, text: raw }
  return { kind, text: sidecarDownText(raw, zh) }
}

export function shortSidecarDetail(detail: string, limit = 180) {
  const text = detail.replace(/\s+/g, " ").trim()
  if (text.length <= limit) return text
  return `${text.slice(0, limit)}…`
}
