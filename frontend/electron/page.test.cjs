const assert = require("node:assert/strict")
const fs = require("node:fs")
const os = require("node:os")
const path = require("node:path")
const test = require("node:test")
const page = require("./page.cjs")

function dist() {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "axiom-page-"))
  fs.mkdirSync(path.join(root, "assets"))
  fs.writeFileSync(path.join(root, "index.html"), "<html></html>")
  fs.writeFileSync(path.join(root, "assets", "app.js"), "console.log(1)")
  return root
}

test("the app root and hashed assets resolve inside dist", () => {
  const root = dist()
  assert.equal(page.resolvePageFile(root, "axiom://local/").file, path.join(root, "index.html"))
  assert.equal(page.resolvePageFile(root, "axiom://local/assets/app.js").file, path.join(root, "assets", "app.js"))
  assert.equal(page.contentType(path.join(root, "assets", "app.js")), "text/javascript; charset=utf-8")
})

test("path traversal and drive-root urls are rejected", () => {
  const root = dist()
  assert.equal(page.resolvePageFile(root, "axiom://local/../../etc/passwd").status, 403)
  assert.equal(page.resolvePageFile(root, "axiom://local/C:/Windows/win.ini").status, 403)
  assert.equal(page.resolvePageFile(root, "file:///C:/assets/app.js").status, 400)
})

test("absolute asset urls are reported before the window is shown", () => {
  assert.match(page.absoluteAssetProblem('<script type="module" src="/assets/index-qYonzEaR.js"></script>'), /filesystem root/)
  assert.equal(page.absoluteAssetProblem('<script type="module" src="./assets/index-qYonzEaR.js"></script>'), "")
})

test("nested routes keep asset urls at the app root", () => {
  const html = page.withAppBase("<head><script src=\"./assets/index.js\"></script></head>")
  assert.match(html, /<base href="\/">/)
  assert.equal(page.assetFallbackUrl("axiom://local/projects/2/assets/index.js"), "axiom://local/assets/index.js")
  assert.equal(page.assetFallbackUrl("axiom://local/assets/index.js"), "")
})

test("the startup page includes the failure detail and recovery actions", () => {
  const html = page.errorPage('did-fail-load ERR_FILE_NOT_FOUND (-6) axiom://local/')
  assert.match(html, /data-startup-error/)
  assert.match(html, /did-fail-load ERR_FILE_NOT_FOUND/)
  assert.match(html, /重试 Retry/)
  assert.match(html, /打开日志文件夹/)
  assert.match(html, /axiom:\/\/local\//)
  assert.match(page.CSP, /http:\/\/127\.0\.0\.1:\*/)
})
