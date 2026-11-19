const fs = require("fs")
const path = require("path")

const CSP = [
  "default-src 'self'",
  "script-src 'self' 'unsafe-inline'",
  "style-src 'self' 'unsafe-inline'",
  "img-src 'self' data: blob:",
  "font-src 'self' data:",
  "connect-src 'self' http://127.0.0.1:* http://localhost:* ws://127.0.0.1:* ws://localhost:*",
  "worker-src 'self' blob:",
  "object-src 'none'",
  "base-uri 'self'",
].join("; ")

const MIME = {
  ".html": "text/html; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".mjs": "text/javascript; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".json": "application/json; charset=utf-8",
  ".svg": "image/svg+xml",
  ".png": "image/png",
  ".ico": "image/x-icon",
  ".woff": "font/woff",
  ".woff2": "font/woff2",
  ".ttf": "font/ttf",
  ".map": "application/json; charset=utf-8",
  ".txt": "text/plain; charset=utf-8",
  ".webp": "image/webp",
}

function contentType(file) {
  return MIME[path.extname(file).toLowerCase()] || "application/octet-stream"
}

function resolvePageFile(distRoot, requestUrl) {
  if (String(requestUrl).includes("..")) return { file: null, status: 403 }
  let pathname = "/"
  try {
    const url = new URL(requestUrl)
    if (url.protocol !== "axiom:") return { file: null, status: 400 }
    pathname = decodeURIComponent(url.pathname || "/")
  } catch {
    return { file: null, status: 400 }
  }
  if (pathname.includes("\0")) return { file: null, status: 400 }
  if (pathname === "/" || pathname === "") pathname = "/index.html"
  const rel = pathname.replace(/^[/\\]+/, "")
  if (!rel || /^[a-zA-Z]:/.test(rel) || rel.startsWith("\\\\")) return { file: null, status: 403 }
  if (rel.split(/[/\\]/).some((part) => part === "..")) return { file: null, status: 403 }
  const root = path.resolve(distRoot)
  const file = path.resolve(root, rel)
  const rootPrefix = root.endsWith(path.sep) ? root : root + path.sep
  if (file !== root && !file.startsWith(rootPrefix)) return { file: null, status: 403 }
  return { file, status: 200 }
}

function withAppBase(html) {
  const text = String(html || "")
  if (/<base\s/i.test(text)) return text
  return text.replace(/<head([^>]*)>/i, "<head$1><base href=\"/\">")
}

function assetFallbackUrl(requestUrl) {
  try {
    const url = new URL(requestUrl)
    const marker = "/assets/"
    const index = url.pathname.indexOf(marker)
    if (index <= 0) return ""
    return `axiom://local${url.pathname.slice(index)}`
  } catch {
    return ""
  }
}

function absoluteAssetProblem(html) {
  const text = String(html || "")
  if (/(\ssrc|\shref)=["']\/assets\//.test(text) || /(\ssrc|\shref)=["']\/src\//.test(text)) {
    return "index.html references /assets or /src at the filesystem root. Under a packaged load those URLs miss the app and the window stays blank."
  }
  return ""
}

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>]/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" })[char])
}

function errorPage(message) {
  const detail = escapeHtml(message || "The interface did not start.")
  return `<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <title>公理 Axiom</title>
  <style>
    html, body { margin: 0; height: 100%; background: #1e1e1e; color: #f4f6fc; font: 14px/1.5 "Segoe UI", sans-serif; }
    main { box-sizing: border-box; min-height: 100%; display: flex; flex-direction: column; justify-content: center; gap: 16px; max-width: 720px; margin: 0 auto; padding: 32px; }
    h1 { font-size: 20px; font-weight: 600; margin: 0; }
    p { margin: 0; color: #c5c8d4; }
    pre { margin: 0; white-space: pre-wrap; overflow: auto; max-height: 240px; padding: 12px; border: 1px solid rgba(255,255,255,.12); background: rgba(0,0,0,.28); border-radius: 8px; }
    div { display: flex; gap: 8px; }
    button { font: inherit; padding: 8px 14px; border-radius: 6px; border: 1px solid transparent; cursor: pointer; }
    #retry { background: #f5b431; color: #172454; }
    #logs { background: transparent; color: #f4f6fc; border-color: rgba(255,255,255,.24); }
  </style>
</head>
<body>
  <main data-startup-error>
    <h1>界面没有启动</h1>
    <p>The studio interface did not start. The details below are also written to main.log.</p>
    <pre id="detail">${detail}</pre>
    <div>
      <button id="retry" type="button">重试 Retry</button>
      <button id="logs" type="button">打开日志文件夹</button>
    </div>
  </main>
  <script>
    document.getElementById("retry").addEventListener("click", function () { location.href = "axiom://local/" })
    document.getElementById("logs").addEventListener("click", function () {
      var bridge = window.axiom
      if (bridge && bridge.openLogs) bridge.openLogs()
    })
  </script>
</body>
</html>`
}

function readPage(file) {
  if (!file || !fs.existsSync(file) || !fs.statSync(file).isFile()) return null
  return fs.readFileSync(file)
}

module.exports = {
  CSP,
  contentType,
  resolvePageFile,
  absoluteAssetProblem,
  withAppBase,
  assetFallbackUrl,
  errorPage,
  readPage,
}
