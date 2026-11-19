const { spawnSync } = require("child_process")
const fs = require("fs")
const net = require("net")

const PREFERRED_PORT = 43124
const BIND_ERROR = /10048|EADDRINUSE|address already in use|error while attempting to bind/i

function isBindError(text) {
  return BIND_ERROR.test(String(text || ""))
}

function isSidecarCommand(line) {
  const text = String(line || "")
  return /uvicorn/i.test(text) && /axiom\.main/i.test(text)
}

function commandLine(pid) {
  const id = Number(pid)
  if (!Number.isInteger(id) || id <= 0) return ""
  if (process.platform === "win32") {
    const result = spawnSync(
      "powershell.exe",
      ["-NoProfile", "-Command", `(Get-CimInstance Win32_Process -Filter "ProcessId=${id}").CommandLine`],
      { encoding: "utf8", windowsHide: true, timeout: 8000 },
    )
    return `${result.stdout || ""}`.trim()
  }
  try {
    return fs.readFileSync(`/proc/${id}/cmdline`).toString("utf8").replaceAll("\0", " ").trim()
  } catch {
    return ""
  }
}

function killProcess(pid) {
  const id = Number(pid)
  if (!Number.isInteger(id) || id <= 0) return
  if (process.platform === "win32") {
    spawnSync("taskkill", ["/PID", String(id), "/T", "/F"], { windowsHide: true, timeout: 8000 })
    return
  }
  try {
    process.kill(id, "SIGTERM")
  } catch {
    // already gone
  }
}

function probe(port) {
  return new Promise((resolve) => {
    const server = net.createServer()
    server.unref()
    const finish = (value) => {
      if (server.listening) server.close(() => resolve(value))
      else resolve(value)
    }
    server.once("error", () => finish(null))
    server.listen({ port, host: "127.0.0.1", exclusive: true }, () => {
      const assigned = server.address()
      finish(assigned && typeof assigned === "object" ? assigned.port : null)
    })
  })
}

async function choosePort(preferred, avoid = new Set()) {
  const hint = Number(preferred)
  if (Number.isInteger(hint) && hint > 0 && hint < 65536 && !avoid.has(hint)) {
    const opened = await probe(hint)
    if (opened === hint) return opened
  }
  for (let attempt = 0; attempt < 8; attempt += 1) {
    const opened = await probe(0)
    if (opened && !avoid.has(opened)) return opened
    if (opened) avoid.add(opened)
  }
  throw new Error("Could not bind 127.0.0.1")
}

async function startWithFallback({ preferred, attempts = 3, avoid = new Set(), start }) {
  let last = { ok: false, bindError: false, port: 0, output: "" }
  for (let attempt = 0; attempt < attempts; attempt += 1) {
    const port = await choosePort(preferred, avoid)
    const result = await start(port)
    last = { ok: false, bindError: false, output: "", ...result, port }
    if (last.ok) return last
    avoid.add(port)
    if (!last.bindError) return last
  }
  return last
}

function readPid(pidFile) {
  try {
    const record = JSON.parse(fs.readFileSync(pidFile, "utf8"))
    const pid = Number(record.pid)
    return Number.isInteger(pid) ? pid : 0
  } catch {
    return 0
  }
}

function reapOrphan(pidFile) {
  const pid = readPid(pidFile)
  if (!pid) return false
  const line = commandLine(pid)
  if (!isSidecarCommand(line)) {
    try {
      fs.unlinkSync(pidFile)
    } catch {
      // already removed
    }
    return false
  }
  killProcess(pid)
  try {
    fs.unlinkSync(pidFile)
  } catch {
    // already removed
  }
  return true
}

function tailText(text, limit = 1800) {
  const value = String(text || "").trim()
  if (value.length <= limit) return value
  return value.slice(value.length - limit)
}

module.exports = {
  PREFERRED_PORT,
  choosePort,
  commandLine,
  isBindError,
  isSidecarCommand,
  killProcess,
  reapOrphan,
  startWithFallback,
  tailText,
}
