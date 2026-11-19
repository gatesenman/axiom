const { app, BrowserWindow, Notification, dialog, ipcMain, protocol, screen, shell } = require("electron")
const fs = require("fs")
const http = require("http")
const path = require("path")
const sidecar = require("./sidecar.cjs")
const { createSupervisor } = require("./supervisor.cjs")
const page = require("./page.cjs")
const windowState = require("./window-state.cjs")

const PAGE_URL = "axiom://local/"
const gpuOff = process.argv.includes("--axiom-disable-gpu") || process.env.AXIOM_DISABLE_GPU === "1"
if (gpuOff) app.disableHardwareAcceleration()

protocol.registerSchemesAsPrivileged([
  {
    scheme: "axiom",
    privileges: {
      standard: true,
      secure: true,
      supportFetchAPI: true,
      corsEnabled: true,
      stream: true,
      codeCache: true,
    },
  },
])

if (process.platform === "win32") app.setAppUserModelId("studio.axiom.desktop")
const DEV_URL = process.env.AXIOM_UI || "http://127.0.0.1:43123"
let backend = null
let logStream = null
let apiBase = ""
let apiBaseReady = false
let attachedExternal = false
let sidecarDialogs = 0
let restartLock = null
let sidecarStatus = { state: "starting", base: "", port: 0, detail: "", restarts: 0, epoch: 0 }
const apiWaiters = []
const avoidedPorts = new Set()
const queuedLogs = []
let mainLogFile = ""

function mainLog(line) {
  const text = `[${new Date().toISOString()}] ${line}\n`
  try {
    if (!mainLogFile) mainLogFile = path.join(app.getPath("userData"), "logs", "main.log")
    fs.mkdirSync(path.dirname(mainLogFile), { recursive: true })
    if (queuedLogs.length) {
      fs.appendFileSync(mainLogFile, queuedLogs.splice(0).join(""))
    }
    fs.appendFileSync(mainLogFile, text)
  } catch {
    queuedLogs.push(text)
  }
}

process.on("uncaughtException", (error) => {
  mainLog(`uncaughtException ${error && error.stack ? error.stack : error}`)
})
process.on("unhandledRejection", (error) => {
  mainLog(`unhandledRejection ${error && error.stack ? error.stack : error}`)
})

function publishApiBase(value) {
  apiBase = value || ""
  apiBaseReady = true
  mainLog(`api base ${apiBase || "(unavailable)"}`)
  for (const resolve of apiWaiters.splice(0)) resolve(apiBase)
}

function backendRoot() {
  if (app.isPackaged) return path.join(process.resourcesPath, "backend")
  return path.resolve(__dirname, "..", "..", "backend")
}

function bundledPython() {
  const besideExe = path.join(path.dirname(process.execPath), "resources", "python", "python.exe")
  const besideResources = process.resourcesPath ? path.join(process.resourcesPath, "python", "python.exe") : ""
  for (const candidate of [besideExe, besideResources]) {
    if (candidate && fs.existsSync(candidate)) return candidate
  }
  return null
}

function pythonBin() {
  if (process.env.AXIOM_PYTHON) return process.env.AXIOM_PYTHON
  if (app.isPackaged) return bundledPython()
  const root = backendRoot()
  const dev = [
    path.join(root, "..", "vendor", "windows", "python", "python.exe"),
    path.join(root, ".venv", "Scripts", "python.exe"),
    path.join(root, ".venv", "bin", "python"),
  ]
  return dev.find((candidate) => fs.existsSync(candidate)) || null
}

function layout(python) {
  const pythonDir = path.dirname(python)
  const parent = path.resolve(pythonDir, "..")
  const packagedBackend = path.join(parent, "backend")
  const backend = fs.existsSync(path.join(packagedBackend, "axiom")) ? packagedBackend : backendRoot()
  const solverCandidates = [
    path.join(parent, "solvers"),
    path.resolve(backendRoot(), "..", "vendor", "windows", "solvers"),
  ]
  const solverDir = solverCandidates.find((candidate) => fs.existsSync(candidate)) || solverCandidates[0]
  return { backend, solverDir, pythonDir }
}

function preferredPort() {
  const hint = Number(process.env.AXIOM_PORT || sidecar.PREFERRED_PORT)
  return Number.isInteger(hint) && hint > 0 ? hint : sidecar.PREFERRED_PORT
}

function userLogPath() {
  return path.join(app.getPath("userData"), "logs", "sidecar.log")
}

function logDir() {
  return path.join(app.getPath("userData"), "logs")
}

function pidFile() {
  return path.join(app.getPath("userData"), "sidecar.pid")
}

function windowStatePath() {
  return path.join(app.getPath("userData"), "window-state.json")
}

function distRoot() {
  return path.join(__dirname, "..", "dist")
}

function healthy(port) {
  return new Promise((resolve) => {
    const request = http.get(`http://127.0.0.1:${port}/api/health`, (response) => {
      response.resume()
      resolve(response.statusCode === 200)
    })
    request.on("error", () => resolve(false))
    request.setTimeout(800, () => {
      request.destroy()
      resolve(false)
    })
  })
}

function stopSidecar() {
  const child = backend
  backend = null
  const alive = child && child.exitCode == null && child.signalCode == null
  if (alive && !child.killed) {
    child.kill()
    if (child.pid) sidecar.killProcess(child.pid)
  }
  if (logStream) {
    logStream.end()
    logStream = null
  }
  try {
    fs.unlinkSync(pidFile())
  } catch {
    // no pid file
  }
}

function openLog() {
  const file = userLogPath()
  fs.mkdirSync(path.dirname(file), { recursive: true })
  if (logStream) logStream.end()
  logStream = fs.createWriteStream(file, { flags: "a" })
  return logStream
}

function runOnce(port) {
  return new Promise((resolve) => {
    stopSidecar()
    const python = pythonBin()
    if (!python) {
      resolve({ ok: false, bindError: false, port, output: "bundled python missing" })
      return
    }
    const paths = layout(python)
    const pathKey = process.platform === "win32" ? "Path" : "PATH"
    const currentPath = process.env[pathKey] || process.env.PATH || ""
    const env = {
      ...process.env,
      PYTHONPATH: paths.backend,
      AXIOM_PORT: String(port),
      AXIOM_SOLVER_DIR: paths.solverDir,
      AXIOM_BUNDLED: python.toLowerCase().endsWith("python.exe") ? "1" : "0",
      PYTHONNOUSERSITE: "1",
    }
    env[pathKey] = [paths.pythonDir, paths.solverDir, currentPath].filter(Boolean).join(path.delimiter)
    const log = openLog()
    log.write(`\n--- ${new Date().toISOString()} port ${port} ---\n`)
    mainLog(`sidecar spawn port ${port} python ${python}`)
    const { spawn } = require("child_process")
    const child = spawn(python, ["-m", "uvicorn", "axiom.main:app", "--host", "127.0.0.1", "--port", String(port)], {
      cwd: paths.backend,
      env,
      windowsHide: true,
      stdio: ["ignore", "pipe", "pipe"],
    })
    backend = child
    fs.mkdirSync(path.dirname(pidFile()), { recursive: true })
    fs.writeFileSync(pidFile(), JSON.stringify({ pid: child.pid, port }))
    let output = ""
    let settled = false
    const finish = (result) => {
      if (settled) return
      settled = true
      resolve(result)
    }
    const take = (chunk) => {
      const text = chunk.toString()
      output += text
      log.write(text)
      if (sidecar.isBindError(output)) {
        stopSidecar()
        finish({ ok: false, bindError: true, port, output })
      }
    }
    child.stdout.on("data", take)
    child.stderr.on("data", take)
    child.on("error", (error) => {
      output += `\n${error.message}\n`
      log.write(`\n${error.message}\n`)
      finish({ ok: false, bindError: sidecar.isBindError(output), port, output })
    })
    child.on("exit", (code, signal) => {
      const line = `\n[sidecar exit] code=${code} signal=${signal || ""}\n`
      if (log.writable) log.write(line)
      mainLog(line.trim())
      if (!settled) finish({ ok: false, bindError: sidecar.isBindError(output), port, output: output + line, child: null })
    })
    ;(async () => {
      for (let attempt = 0; attempt < 60; attempt += 1) {
        if (settled) return
        if (await healthy(port)) {
          finish({ ok: true, bindError: false, port, output, child })
          return
        }
        await new Promise((done) => setTimeout(done, 500))
      }
      if (!settled) {
        stopSidecar()
        finish({ ok: false, bindError: sidecar.isBindError(output), port, output })
      }
    })()
  })
}

async function launchSidecar(preferred) {
  return sidecar.startWithFallback({
    preferred,
    attempts: 3,
    avoid: avoidedPorts,
    start: (port) => runOnce(port),
  })
}

async function showSidecarFailure(result) {
  const file = userLogPath()
  let logged = ""
  try {
    logged = fs.readFileSync(file, "utf8")
  } catch {
    logged = result.output || ""
  }
  const tail = sidecar.tailText(logged)
  const detail = [
    "窗口还在，但 Python 求解进程已经退出或没有在监听，所以登录连不上。",
    "The window is still open, but the Python sidecar has exited or is not listening, so sign-in cannot connect.",
    "公理会自动重启它。若仍失败，请打开日志，或退出公理后重新打开。",
    "Axiom restarts it automatically. If it stays down, open the logs or quit and relaunch.",
    "",
    result.output || "",
    "",
    `日志 Log: ${file}`,
    `主进程 Main: ${mainLogFile || path.join(logDir(), "main.log")}`,
    "",
    tail || "(no output)",
  ].join("\n")
  mainLog(`sidecar failed port ${result.port}`)
  const choice = await dialog.showMessageBox({
    type: "error",
    title: "公理 Axiom",
    message: "求解服务连不上",
    detail,
    buttons: ["重试 Retry", "打开日志文件夹 Open log folder", "关闭 Close"],
    defaultId: 0,
    cancelId: 2,
    noLink: true,
  })
  if (choice.response === 1) {
    await shell.openPath(path.dirname(file))
    return "log"
  }
  if (choice.response === 0) return "retry"
  return "close"
}

function notifySidecar(body) {
  if (!Notification.isSupported()) return
  try {
    const note = new Notification({ title: "公理 Axiom", body })
    note.show()
  } catch (error) {
    mainLog(`notify failed ${error.message}`)
  }
}

function broadcastSidecar(status) {
  sidecarStatus = {
    state: status.state,
    base: status.base || "",
    port: status.port || 0,
    detail: status.detail || "",
    restarts: status.restarts || 0,
    epoch: status.epoch || 0,
  }
  if (status.state === "up" && status.base) publishApiBase(status.base)
  if (status.state === "down") publishApiBase("")
  for (const win of BrowserWindow.getAllWindows()) {
    if (!win.isDestroyed()) win.webContents.send("axiom:sidecar", sidecarStatus)
  }
}

async function explainSidecar(status) {
  if (sidecarDialogs > 0) return
  sidecarDialogs += 1
  try {
    let choice = await showSidecarFailure({ port: status.port, output: status.detail })
    while (choice === "log" && supervisor.current().state !== "up") {
      const current = supervisor.current()
      choice = await showSidecarFailure({ port: current.port, output: current.detail })
    }
    if (choice === "retry" && supervisor.current().state !== "up") {
      sidecarDialogs -= 1
      await supervisor.start(preferredPort())
      return
    }
  } finally {
    if (sidecarDialogs > 0) sidecarDialogs -= 1
  }
}

function onSupervisorStatus(status) {
  const previous = sidecarStatus.state
  broadcastSidecar(status)
  if (status.state === "restarting" && previous !== "restarting") {
    mainLog(`sidecar restarting ${status.detail}`)
    notifySidecar("求解服务已断开，正在重新启动。 The solver service dropped. Restarting.")
    void explainSidecar(status)
  } else if (status.state === "down" && previous !== "down") {
    mainLog(`sidecar down ${status.detail}`)
    void explainSidecar(status)
  } else if (status.state === "up") {
    mainLog(`sidecar listening ${status.port}`)
  }
}

const supervisor = createSupervisor({
  maxRestarts: 3,
  restartDelayMs: 600,
  start: async (preferred) => {
    const hint = preferred || preferredPort()
    const result = await launchSidecar(hint)
    return { ...result, child: result && result.ok ? backend : null }
  },
  onStatus: (status) => onSupervisorStatus(status),
})

async function ensureBackend() {
  sidecar.reapOrphan(pidFile())
  const preferred = preferredPort()
  mainLog(`preferred port ${preferred}`)
  if (!app.isPackaged && (await healthy(preferred))) {
    attachedExternal = true
    publishApiBase(`http://127.0.0.1:${preferred}`)
    sidecarStatus = { state: "up", base: apiBase, port: preferred, detail: "", restarts: 0, epoch: 0 }
    mainLog(`sidecar attach ${preferred}`)
    return true
  }
  const result = await supervisor.start(preferred)
  return Boolean(result && result.ok)
}

function windowIcon() {
  const candidates = [
    path.join(__dirname, "..", "dist", "icon-256.png"),
    path.join(__dirname, "..", "public", "icon-256.png"),
  ]
  return candidates.find((candidate) => fs.existsSync(candidate))
}

function readSavedWindow() {
  try {
    return JSON.parse(fs.readFileSync(windowStatePath(), "utf8"))
  } catch {
    return null
  }
}

function currentDisplays() {
  const primaryId = screen.getPrimaryDisplay().id
  return screen.getAllDisplays().map((display) => ({
    id: display.id,
    primary: display.id === primaryId,
    scaleFactor: display.scaleFactor,
    workArea: display.workArea,
    bounds: display.bounds,
  }))
}

function rememberWindow(win) {
  if (!win || win.isDestroyed()) return
  const bounds = typeof win.getNormalBounds === "function" ? win.getNormalBounds() : win.getBounds()
  const payload = {
    x: bounds.x,
    y: bounds.y,
    width: bounds.width,
    height: bounds.height,
    maximized: win.isMaximized(),
    minimized: false,
  }
  try {
    fs.writeFileSync(windowStatePath(), JSON.stringify(payload))
  } catch (error) {
    mainLog(`window-state write failed ${error.message}`)
  }
}

function showFailure(win, detail) {
  if (win && win.__axiomFailure) return
  if (win) win.__axiomFailure = true
  const text = `${detail}\n\n日志 Log: ${mainLogFile || path.join(logDir(), "main.log")}`
  mainLog(`startup error ${detail}`)
  if (win && !win.isDestroyed()) {
    const html = page.errorPage(text)
    win.loadURL(`data:text/html;charset=utf-8,${encodeURIComponent(html)}`).catch((error) => {
      mainLog(`error page failed ${error.message}`)
    })
  }
  dialog.showMessageBox(win && !win.isDestroyed() ? win : undefined, {
    type: "error",
    title: "公理 Axiom",
    message: "界面没有启动",
    detail: text,
    buttons: ["关闭 Close"],
    noLink: true,
  }).catch((error) => mainLog(`error dialog failed ${error.message}`))
}

function registerPageProtocol() {
  protocol.handle("axiom", (request) => {
    try {
      const resolved = page.resolvePageFile(distRoot(), request.url)
      if (!resolved.file) {
        mainLog(`page ${resolved.status} ${request.url}`)
        return new Response("not found", { status: resolved.status || 404, headers: { "Content-Type": "text/plain; charset=utf-8" } })
      }
      let file = resolved.file
      if (!fs.existsSync(file) || !fs.statSync(file).isFile()) {
        const fallback = page.assetFallbackUrl(request.url)
        const fallbackFile = fallback ? page.resolvePageFile(distRoot(), fallback).file : ""
        if (fallbackFile && fs.existsSync(fallbackFile) && fs.statSync(fallbackFile).isFile()) {
          file = fallbackFile
          mainLog(`page asset fallback ${request.url} -> ${fallback}`)
        } else if (!path.extname(file)) file = path.join(distRoot(), "index.html")
        if (!fs.existsSync(file)) {
          mainLog(`page 404 ${request.url}`)
          return new Response(page.errorPage(`Missing ${request.url}`), {
            status: 404,
            headers: { "Content-Type": "text/html; charset=utf-8" },
          })
        }
      }
      let body = fs.readFileSync(file)
      if (path.extname(file).toLowerCase() === ".html") body = Buffer.from(page.withAppBase(body.toString("utf8")))
      if (file.endsWith(`${path.sep}index.html`) || file.endsWith("/index.html")) {
        const problem = page.absoluteAssetProblem(body.toString("utf8"))
        if (problem) {
          mainLog(problem)
          return new Response(page.errorPage(problem), {
            status: 500,
            headers: { "Content-Type": "text/html; charset=utf-8", "Content-Security-Policy": page.CSP },
          })
        }
      }
      const headers = {
        "Content-Type": page.contentType(file),
        "Content-Length": String(body.length),
      }
      if (path.extname(file).toLowerCase() === ".html") headers["Content-Security-Policy"] = page.CSP
      return new Response(new Uint8Array(body), { status: 200, headers })
    } catch (error) {
      mainLog(`page error ${request.url} ${error.stack || error.message}`)
      return new Response(page.errorPage(error.message), {
        status: 500,
        headers: { "Content-Type": "text/html; charset=utf-8", "Content-Security-Policy": page.CSP },
      })
    }
  })
}

function wireConsole(win) {
  win.webContents.on("console-message", (event) => {
    const record = event && typeof event === "object" ? event : {}
    const text = typeof record.message === "string" ? record.message : ""
    const severity = record.level
    const where = `${record.sourceId || ""}:${record.lineNumber || record.line || ""}`
    const warn = severity === "warning" || severity === "error" || severity === 2 || severity === 3
    if (!warn) return
    mainLog(`console ${severity} ${where} ${text}`)
  })
  win.webContents.on("preload-error", (_event, preloadPath, error) => {
    showFailure(win, `Preload failed (${preloadPath}): ${error && (error.stack || error.message) || error}`)
  })
  win.webContents.on("did-fail-load", (_event, code, description, url, isMainFrame) => {
    mainLog(`did-fail-load ${code} ${description} ${url} main=${isMainFrame}`)
    if (!isMainFrame || code === -3) return
    showFailure(win, `did-fail-load ${description} (${code}) ${url}`)
  })
  win.webContents.on("did-finish-load", () => {
    mainLog(`did-finish-load ${win.webContents.getURL()}`)
    win.webContents.send("axiom:sidecar", sidecarStatus)
    setTimeout(() => {
      if (win.isDestroyed()) return
      win.webContents.executeJavaScript(`({
        children: document.getElementById("root") ? document.getElementById("root").childElementCount : -1,
        boot: (document.getElementById("boot-error") && document.getElementById("boot-error").dataset.detail) || "",
        href: location.href,
        scripts: Array.from(document.scripts).map((node) => node.src || "inline").slice(0, 12)
      })`, false).then((state) => {
        mainLog(`paint ${JSON.stringify(state)}`)
        if (!state || state.children > 0 || String(state.href || "").startsWith("data:")) return
        const detail = state.boot || `The page at ${state.href} loaded but #root stayed empty.`
        showFailure(win, `${detail}\nScripts:\n${(state.scripts || []).join("\n")}`)
      }).catch((error) => mainLog(`paint check failed ${error.message}`))
    }, 10000)
  })
  win.webContents.on("render-process-gone", (_event, details) => {
    const detail = `render-process-gone ${details.reason} exit ${details.exitCode}`
    mainLog(detail)
    if (details.reason === "clean-exit") return
    const hint = gpuOff ? "" : "\nRelaunch with --axiom-disable-gpu if this crash repeats."
    showFailure(win, detail + hint)
  })
  win.on("unresponsive", () => mainLog("window unresponsive"))
  win.on("responsive", () => mainLog("window responsive"))
}

function createWindow() {
  const displays = currentDisplays()
  const saved = readSavedWindow()
  const placed = windowState.placeWindow(saved, displays, { width: 1440, height: 920 })
  mainLog(`displays ${JSON.stringify(displays.map((display) => ({ primary: display.primary, scaleFactor: display.scaleFactor, workArea: display.workArea })))}`)
  mainLog(`window ${JSON.stringify(placed)} saved ${JSON.stringify(saved)}`)
  const preload = path.join(__dirname, "preload.cjs")
  if (!fs.existsSync(preload)) mainLog(`preload missing ${preload}`)
  const win = new BrowserWindow({
    x: placed.x,
    y: placed.y,
    width: placed.width,
    height: placed.height,
    minWidth: Math.min(960, placed.width),
    minHeight: Math.min(640, placed.height),
    show: false,
    title: "公理 Axiom",
    backgroundColor: "#1e1e1e",
    frame: false,
    icon: windowIcon(),
    webPreferences: {
      preload,
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: false,
      allowRunningInsecureContent: true,
    },
  })
  let shown = false
  const reveal = (why) => {
    if (shown || win.isDestroyed()) return
    shown = true
    if (win.isMinimized()) win.restore()
    if (placed.maximized) win.maximize()
    win.show()
    win.focus()
    mainLog(`show ${why} bounds ${JSON.stringify(win.getBounds())}`)
  }
  win.once("ready-to-show", () => reveal("ready-to-show"))
  setTimeout(() => reveal("fallback-timeout"), 8000)
  const save = () => rememberWindow(win)
  win.on("move", save)
  win.on("resize", save)
  win.on("close", save)
  wireConsole(win)
  const dev = process.env.ELECTRON_DEV === "1"
  const target = dev ? DEV_URL : PAGE_URL
  mainLog(`loadURL ${target} packaged=${app.isPackaged} gpuOff=${gpuOff} exec=${process.execPath}`)
  if (!dev) {
    const indexFile = path.join(distRoot(), "index.html")
    let html = ""
    try {
      html = fs.readFileSync(indexFile, "utf8")
    } catch (error) {
      showFailure(win, `Could not read ${indexFile}: ${error.message}`)
      reveal("index-missing")
      return win
    }
    const problem = page.absoluteAssetProblem(html)
    if (problem) {
      showFailure(win, problem)
      reveal("absolute-assets")
      return win
    }
    const src = html.match(/<script[^>]*src=["']([^"']+)["']/)
    mainLog(`index script ${src ? src[1] : "(none)"}`)
  }
  win.loadURL(target).catch((error) => showFailure(win, `loadURL ${target} failed: ${error.message}`))
  return win
}

ipcMain.handle("axiom:api-base", () => {
  if (apiBaseReady) return apiBase
  return new Promise((resolve) => apiWaiters.push(resolve))
})
ipcMain.handle("axiom:sidecar-status", () => sidecarStatus)
ipcMain.handle("axiom:restart-sidecar", () => {
  if (attachedExternal) {
    return {
      ...sidecarStatus,
      state: "down",
      detail: "The development sidecar is not owned by this window. Restart the API process.",
    }
  }
  if (restartLock) return restartLock.then(() => supervisor.current())
  if (sidecarStatus.state === "restarting") return sidecarStatus
  restartLock = supervisor.start(0).finally(() => {
    restartLock = null
  })
  return restartLock.then(() => supervisor.current())
})
ipcMain.handle("axiom:open-logs", async () => {
  const dir = logDir()
  fs.mkdirSync(dir, { recursive: true })
  const result = await shell.openPath(dir)
  mainLog(`open logs ${dir} ${result || "ok"}`)
  if (result) throw new Error(result)
  return dir
})
ipcMain.on("window:minimize", (event) => BrowserWindow.fromWebContents(event.sender)?.minimize())
ipcMain.on("window:maximize", (event) => {
  const target = BrowserWindow.fromWebContents(event.sender)
  if (!target) return
  if (target.isMaximized()) target.unmaximize()
  else target.maximize()
})
ipcMain.on("window:close", (event) => BrowserWindow.fromWebContents(event.sender)?.close())
ipcMain.handle("notify", (_event, payload) => {
  if (!Notification.isSupported()) return false
  const note = new Notification({ title: String(payload?.title || "公理 Axiom"), body: String(payload?.body || "") })
  note.show()
  return true
})

app.on("child-process-gone", (_event, details) => {
  mainLog(`child-process-gone ${details.type} ${details.reason} exit ${details.exitCode}`)
})

app.whenReady().then(async () => {
  mainLog(`ready version ${app.getVersion()} packaged=${app.isPackaged} userData=${app.getPath("userData")} argv=${process.argv.slice(1).join(" ")}`)
  registerPageProtocol()
  try {
    await ensureBackend()
  } catch (error) {
    mainLog(`backend ${error.stack || error}`)
    publishApiBase("")
  }
  createWindow()
})

app.on("before-quit", () => {
  mainLog("before-quit")
  supervisor.stop()
  stopSidecar()
})

app.on("window-all-closed", () => {
  supervisor.stop()
  stopSidecar()
  if (process.platform !== "darwin") app.quit()
})
