const MIN_VISIBLE = 80

function overlap(windowRect, work) {
  const width = Math.max(0, Math.min(windowRect.x + windowRect.width, work.x + work.width) - Math.max(windowRect.x, work.x))
  const height = Math.max(0, Math.min(windowRect.y + windowRect.height, work.y + work.height) - Math.max(windowRect.y, work.y))
  return { width, height, area: width * height }
}

function centerIn(work, width, height) {
  const nextWidth = Math.max(1, Math.min(width, work.width))
  const nextHeight = Math.max(1, Math.min(height, work.height))
  return {
    x: Math.round(work.x + (work.width - nextWidth) / 2),
    y: Math.round(work.y + (work.height - nextHeight) / 2),
    width: Math.round(nextWidth),
    height: Math.round(nextHeight),
    maximized: false,
  }
}

function placeWindow(saved, displays, fallback) {
  const list = Array.isArray(displays) && displays.length
    ? displays
    : [{ workArea: { x: 0, y: 0, width: fallback.width, height: fallback.height }, scaleFactor: 1, primary: true }]
  const primary = list.find((display) => display.primary) || list[0]
  const fresh = (reason) => ({ ...centerIn(primary.workArea, fallback.width, fallback.height), reason })
  if (!saved || typeof saved !== "object") return fresh("missing")
  const width = Number(saved.width)
  const height = Number(saved.height)
  const x = Number(saved.x)
  const y = Number(saved.y)
  if (![width, height, x, y].every((value) => Number.isFinite(value))) return fresh("invalid")
  if (width < 200 || height < 160) return fresh("invalid")
  const rect = { x, y, width, height }
  let host = null
  let best = 0
  for (const display of list) {
    const hit = overlap(rect, display.workArea)
    if (hit.width >= MIN_VISIBLE && hit.height >= MIN_VISIBLE && hit.area > best) {
      host = display
      best = hit.area
    }
  }
  if (!host) return fresh("offscreen")
  const work = host.workArea
  const nextWidth = Math.min(width, work.width)
  const nextHeight = Math.min(height, work.height)
  let nextX = x
  let nextY = y
  if (nextX < work.x) nextX = work.x
  if (nextY < work.y) nextY = work.y
  if (nextX + nextWidth > work.x + work.width) nextX = work.x + work.width - nextWidth
  if (nextY + nextHeight > work.y + work.height) nextY = work.y + work.height - nextHeight
  return {
    x: Math.round(nextX),
    y: Math.round(nextY),
    width: Math.round(nextWidth),
    height: Math.round(nextHeight),
    maximized: Boolean(saved.maximized) && !saved.minimized,
    reason: saved.minimized ? "restored" : "ok",
  }
}

module.exports = { placeWindow, MIN_VISIBLE }
