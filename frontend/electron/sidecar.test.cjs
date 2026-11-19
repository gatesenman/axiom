const assert = require("node:assert/strict")
const { spawn } = require("node:child_process")
const fs = require("node:fs")
const net = require("node:net")
const os = require("node:os")
const path = require("node:path")
const test = require("node:test")
const sidecar = require("./sidecar.cjs")

function listen(port) {
  return new Promise((resolve, reject) => {
    const server = net.createServer()
    server.once("error", reject)
    server.listen(port, "127.0.0.1", () => resolve(server))
  })
}

function close(server) {
  return new Promise((resolve) => server.close(() => resolve()))
}

test("preferred port is kept when it is free", async () => {
  const held = await listen(0)
  const preferred = held.address().port
  await close(held)
  const chosen = await sidecar.choosePort(preferred)
  assert.equal(chosen, preferred)
})

test("occupied preferred port falls back to a different bindable port", async () => {
  const held = await listen(0)
  const preferred = held.address().port
  try {
    const chosen = await sidecar.choosePort(preferred)
    assert.notEqual(chosen, preferred)
    const probe = await listen(chosen)
    assert.equal(probe.address().port, chosen)
    await close(probe)
  } finally {
    await close(held)
  }
})

test("a bind error on the first port retries with another port", async () => {
  const held = await listen(0)
  const preferred = held.address().port
  const seen = []
  try {
    const result = await sidecar.startWithFallback({
      preferred,
      attempts: 3,
      start: async (port) => {
        seen.push(port)
        if (seen.length === 1) {
          return { ok: false, bindError: true, output: "[Errno 10048] error while attempting to bind on address ('127.0.0.1', 43124)" }
        }
        return { ok: true, output: "Application startup complete" }
      },
    })
    assert.equal(result.ok, true)
    assert.equal(seen.length, 2)
    assert.notEqual(seen[0], preferred)
    assert.notEqual(seen[1], seen[0])
    assert.equal(sidecar.isBindError(seen.length ? "[Errno 10048] error while attempting to bind on address ('127.0.0.1', 43124)" : ""), true)
  } finally {
    await close(held)
  }
})

test("recognizes Windows bind failures", () => {
  assert.equal(sidecar.isBindError("[Errno 10048] error while attempting to bind on address ('127.0.0.1', 43124)"), true)
  assert.equal(sidecar.isBindError("OSError: [Errno 98] Address already in use"), true)
  assert.equal(sidecar.isBindError("Application startup complete"), false)
})

test("startup kills an orphaned sidecar and leaves other processes", async () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "axiom-sidecar-"))
  const pidFile = path.join(dir, "sidecar.pid")
  const orphan = spawn(process.execPath, ["-e", "setInterval(() => {}, 1000)", "uvicorn", "axiom.main:app"], { stdio: "ignore" })
  const bystander = spawn(process.execPath, ["-e", "setInterval(() => {}, 1000)"], { stdio: "ignore" })
  await new Promise((resolve) => setTimeout(resolve, 150))
  fs.writeFileSync(pidFile, JSON.stringify({ pid: orphan.pid }))
  try {
    assert.equal(sidecar.reapOrphan(pidFile), true)
    assert.equal(fs.existsSync(pidFile), false)
    await new Promise((resolve) => orphan.once("exit", resolve))
    assert.equal(orphan.exitCode !== null || orphan.signalCode !== null, true)
    assert.equal(bystander.exitCode, null)
  } finally {
    orphan.kill()
    bystander.kill()
    fs.rmSync(dir, { recursive: true, force: true })
  }
})
