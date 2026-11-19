const assert = require("node:assert/strict")
const { spawn } = require("node:child_process")
const http = require("node:http")
const test = require("node:test")
const sidecar = require("./sidecar.cjs")
const { createSupervisor } = require("./supervisor.cjs")

const CHILD = `
const http = require("http")
const port = Number(process.env.AXIOM_TEST_PORT)
http.createServer((req, res) => {
  res.writeHead(200, { "content-type": "application/json" })
  res.end(JSON.stringify({ ok: true, port }))
}).listen(port, "127.0.0.1")
`

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms))
}

function healthy(port) {
  return new Promise((resolve) => {
    const request = http.get(`http://127.0.0.1:${port}/api/health`, (response) => {
      response.resume()
      resolve(response.statusCode === 200)
    })
    request.on("error", () => resolve(false))
    request.setTimeout(300, () => {
      request.destroy()
      resolve(false)
    })
  })
}

async function spawnSidecar() {
  const port = await sidecar.choosePort(0)
  const child = spawn(process.execPath, ["-e", CHILD], {
    env: { ...process.env, AXIOM_TEST_PORT: String(port) },
    stdio: "ignore",
  })
  for (let attempt = 0; attempt < 50; attempt += 1) {
    if (await healthy(port)) return { ok: true, port, output: "", child }
    if (child.exitCode != null) return { ok: false, port, output: "sidecar exited before health", child: null }
    await sleep(20)
  }
  child.kill()
  return { ok: false, port, output: "health timeout", child: null }
}

test("killing the sidecar mid-session restarts it and health recovers", async () => {
  let owned = null
  const seen = []
  const supervisor = createSupervisor({
    maxRestarts: 3,
    restartDelayMs: 40,
    onStatus: (status) => seen.push(status.state),
    start: async () => {
      const result = await spawnSidecar()
      owned = result.child
      return result
    },
  })
  try {
    const first = await supervisor.start(0)
    assert.equal(first.ok, true)
    assert.equal(supervisor.current().state, "up")
    const firstEpoch = supervisor.current().epoch
    const firstPort = supervisor.current().port
    assert.equal(await healthy(firstPort), true)
    owned.kill()
    const started = Date.now()
    let recovered = supervisor.current()
    while (Date.now() - started < 8000) {
      recovered = supervisor.current()
      if (recovered.state === "up" && recovered.epoch > firstEpoch) break
      await sleep(40)
    }
    assert.equal(recovered.state, "up", recovered.detail)
    assert.ok(recovered.epoch > firstEpoch)
    assert.equal(await healthy(recovered.port), true)
    assert.ok(seen.includes("restarting"))
    assert.equal(recovered.detail.includes("登录没有成功"), false)
  } finally {
    supervisor.stop()
  }
})

test("a sidecar that cannot restart surfaces an actionable error", async () => {
  let calls = 0
  let owned = null
  const supervisor = createSupervisor({
    maxRestarts: 2,
    restartDelayMs: 5,
    start: async () => {
      calls += 1
      if (calls === 1) {
        const child = spawn(process.execPath, ["-e", "setTimeout(() => {}, 30000)"], { stdio: "ignore" })
        owned = child
        return { ok: true, port: 9, output: "", child }
      }
      return { ok: false, port: 9, output: "connect ECONNREFUSED 127.0.0.1:9", child: null }
    },
  })
  try {
    await supervisor.start(0)
    assert.equal(supervisor.current().state, "up")
    owned.kill()
    const started = Date.now()
    let status = supervisor.current()
    while (Date.now() - started < 4000) {
      status = supervisor.current()
      if (status.state === "down") break
      await sleep(20)
    }
    assert.equal(status.state, "down")
    assert.match(status.detail, /ECONNREFUSED/)
    assert.match(status.detail, /sidecar log/i)
    assert.match(status.detail, /relaunch/i)
    assert.equal(status.detail.includes("登录没有成功"), false)
    assert.ok(calls >= 2)
  } finally {
    supervisor.stop()
  }
})
