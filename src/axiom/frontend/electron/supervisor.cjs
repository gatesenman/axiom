"use strict"

/**
 * Keep a sidecar process alive for the desktop window.
 * An unexpected exit schedules another start. Repeated failures stop
 * with an actionable detail the UI can show.
 */

function createSupervisor(options) {
  const start = options.start
  const onStatus = options.onStatus || (() => {})
  const maxRestarts = Number.isInteger(options.maxRestarts) ? options.maxRestarts : 3
  const restartDelayMs = Number.isFinite(options.restartDelayMs) ? options.restartDelayMs : 400
  const sleep = options.sleep || ((ms) => new Promise((resolve) => setTimeout(resolve, ms)))

  let generation = 0
  let wanted = false
  let child = null
  let port = 0
  let restarts = 0
  let epoch = 0
  let status = { state: "idle", base: "", port: 0, detail: "", restarts: 0, epoch: 0 }

  function emit(next) {
    status = next
    onStatus(status)
    return status
  }

  function attach(proc, gen) {
    const onExit = (code, signal) => {
      if (gen !== generation || !wanted) return
      if (proc !== child) return
      child = null
      void onUnexpectedExit(code, signal, gen)
    }
    if (typeof proc.once === "function") proc.once("exit", onExit)
    else if (typeof proc.on === "function") proc.on("exit", onExit)
  }

  async function onUnexpectedExit(code, signal, gen) {
    const detail = `sidecar exited code=${code ?? "null"} signal=${signal || "none"} port=${port}`
    if (restarts >= maxRestarts) {
      wanted = false
      emit({
        state: "down",
        base: "",
        port,
        detail: `${detail}. Retries exhausted (${restarts}). Open the sidecar log and relaunch Axiom.`,
        restarts,
        epoch,
      })
      return
    }
    restarts += 1
    emit({ state: "restarting", base: "", port, detail, restarts, epoch })
    await sleep(restartDelayMs)
    if (gen !== generation || !wanted) return
    await boot(0, gen)
  }

  async function boot(preferred, gen) {
    let result
    try {
      result = await start(preferred)
    } catch (error) {
      result = { ok: false, port: 0, output: error && error.message ? error.message : String(error), child: null }
    }
    if (gen !== generation || !wanted) {
      if (result && result.child && typeof result.child.kill === "function") result.child.kill()
      return result
    }
    if (!result || !result.ok) {
      const detail = String((result && result.output) || `failed to bind port ${result && result.port ? result.port : 0}`).trim().slice(-800)
      const failedPort = result && result.port ? result.port : 0
      if (restarts >= maxRestarts) {
        wanted = false
        emit({
          state: "down",
          base: "",
          port: failedPort,
          detail: `${detail}. Retries exhausted (${restarts}). Open the sidecar log and relaunch Axiom.`,
          restarts,
          epoch,
        })
        return result
      }
      restarts += 1
      emit({ state: "restarting", base: "", port: failedPort, detail, restarts, epoch })
      await sleep(restartDelayMs)
      if (gen !== generation || !wanted) return result
      return boot(0, gen)
    }
    child = result.child || null
    port = result.port
    restarts = 0
    epoch += 1
    emit({ state: "up", base: `http://127.0.0.1:${port}`, port, detail: "", restarts: 0, epoch })
    if (child) attach(child, gen)
    return result
  }

  return {
    start(preferred = 0) {
      generation += 1
      wanted = true
      restarts = 0
      const previous = child
      child = null
      if (previous && typeof previous.kill === "function") previous.kill()
      return boot(preferred, generation)
    },
    stop() {
      generation += 1
      wanted = false
      const current = child
      child = null
      if (current && typeof current.kill === "function") current.kill()
    },
    current() {
      return status
    },
  }
}

module.exports = { createSupervisor }
