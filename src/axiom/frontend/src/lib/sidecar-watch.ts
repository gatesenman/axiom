export type SidecarPhase = "unknown" | "starting" | "up" | "restarting" | "down"

export function foldHealth(prev: { misses: number; phase: SidecarPhase }, probe: "ok" | "fail") {
  if (probe === "ok") return { misses: 0, phase: "up" as const, restart: false }
  const misses = prev.misses + 1
  if (misses >= 3) return { misses, phase: "down" as const, restart: prev.phase !== "down" }
  if (misses >= 2) return { misses, phase: "restarting" as const, restart: false }
  return { misses, phase: prev.phase, restart: false }
}
