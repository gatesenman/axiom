import { useEffect, useState } from "react"
import { useTranslation } from "react-i18next"
import { noteApiBase, resolveApiBase } from "@/lib/api"
import { shortSidecarDetail } from "@/lib/login-error"
import { foldHealth, type SidecarPhase } from "@/lib/sidecar-watch"

export type SidecarStatus = {
  state: SidecarPhase
  base: string
  detail: string
  port: number
  restarts: number
}

const initial: SidecarStatus = { state: "unknown", base: "", detail: "", port: 0, restarts: 0 }
let snapshot: SidecarStatus = initial
let misses = 0
let phase: SidecarPhase = "unknown"
const listeners = new Set<() => void>()
let loopStarted = false
let restarting = false

function publish(next: SidecarStatus) {
  snapshot = next
  phase = next.state
  for (const listener of listeners) listener()
}

function applyAnnounced(next: SidecarStatus) {
  if (next.base) noteApiBase(next.base)
  else if (next.state === "down") noteApiBase("")
  if (next.state === "up") misses = 0
  phase = next.state
  publish({
    state: next.state,
    base: next.base || "",
    detail: next.detail || "",
    port: next.port || 0,
    restarts: next.restarts || 0,
  })
}

async function askRestart() {
  const bridge = window.axiom
  if (!bridge?.restartSidecar || restarting) return
  restarting = true
  try {
    const next = await bridge.restartSidecar()
    if (next) applyAnnounced(next as SidecarStatus)
  } catch (error) {
    const detail = error instanceof Error ? error.message : String(error)
    publish({ ...snapshot, state: "down", detail })
  } finally {
    restarting = false
  }
}

async function probeOnce() {
  const bridge = window.axiom
  let base = ""
  try {
    base = await resolveApiBase()
  } catch {
    base = ""
  }
  const desktop = Boolean(bridge?.getApiBase)
  if (!base && desktop) {
    const folded = foldHealth({ misses, phase }, "fail")
    misses = folded.misses
    phase = folded.phase
    publish({ ...snapshot, state: folded.phase, base: "", detail: snapshot.detail || "solver service is not running" })
    if (folded.restart) void askRestart()
    return
  }
  try {
    const response = await fetch(`${base}/api/health`, { cache: "no-store" })
    const type = response.headers.get("content-type") || ""
    if (!response.ok || !type.includes("json")) throw new Error(`HTTP ${response.status}`)
    const body = (await response.json()) as { ok?: boolean }
    if (!body?.ok) throw new Error("health not ok")
    misses = 0
    phase = "up"
    publish({ ...snapshot, state: "up", base, detail: "" })
  } catch (error) {
    const folded = foldHealth({ misses, phase }, "fail")
    misses = folded.misses
    phase = folded.phase
    const detail = error instanceof Error ? error.message : String(error)
    publish({ ...snapshot, state: folded.phase, detail: snapshot.detail || detail })
    if (folded.restart) void askRestart()
  }
}

function ensureLoop() {
  if (loopStarted) return
  loopStarted = true
  const bridge = window.axiom
  if (bridge?.onSidecar) bridge.onSidecar((payload) => applyAnnounced(payload as SidecarStatus))
  if (bridge?.sidecarStatus) void bridge.sidecarStatus().then((payload) => applyAnnounced(payload as SidecarStatus)).catch(() => undefined)
  void probeOnce()
  window.setInterval(() => void probeOnce(), 2000)
}

export function useSidecar() {
  const [status, setStatus] = useState(snapshot)
  useEffect(() => {
    ensureLoop()
    const listener = () => setStatus(snapshot)
    listeners.add(listener)
    setStatus(snapshot)
    return () => {
      listeners.delete(listener)
    }
  }, [])
  return status
}

export function SidecarBanner() {
  const { t } = useTranslation()
  const status = useSidecar()
  if (status.state === "up" || status.state === "unknown" || status.state === "starting") return null
  const text = status.state === "restarting" ? t("login.restarting") : t("login.down")
  const detail = shortSidecarDetail(status.detail)
  return (
    <div role="status" data-sidecar={status.state} className="no-drag flex shrink-0 items-center gap-2 border-b bg-destructive/10 px-3 py-1 text-xs">
      <span className="min-w-0 flex-1 truncate">{text}{detail ? ` ${detail}` : ""}</span>
      <button type="button" className="shrink-0 underline" onClick={() => void window.axiom?.restartSidecar?.()}>{t("login.reconnect")}</button>
      <button type="button" className="shrink-0 underline" onClick={() => void window.axiom?.openLogs?.()}>{t("login.openLogs")}</button>
    </div>
  )
}
