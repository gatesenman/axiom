import assert from "node:assert/strict"
import test from "node:test"
import { classifyLoginError, loginToast, sidecarDownText } from "./login-error.ts"

test("a refused password stays a password error", () => {
  const error = { name: "ApiError", status: 401, message: "用户名或密码不正确。", messageEn: "Incorrect username or password." }
  assert.equal(classifyLoginError(error), "password")
  const toast = loginToast(error, true, "登录没有成功")
  assert.equal(toast.kind, "password")
  assert.equal(toast.text, "用户名或密码不正确。")
  assert.equal(toast.text.includes("侧车"), false)
})

test("a dead sidecar is not the generic sign-in failure", () => {
  const error = new TypeError("Failed to fetch")
  assert.equal(classifyLoginError(error), "sidecar")
  const toast = loginToast(error, true, "登录没有成功")
  assert.equal(toast.kind, "sidecar")
  assert.match(toast.text, /侧车/)
  assert.equal(toast.text.includes("登录没有成功"), false)
  assert.match(toast.text, /Failed to fetch/)
  assert.match(sidecarDownText("", false), /sidecar may have exited/)
})

test("an empty desktop base is a sidecar failure", () => {
  const error = { name: "ApiError", status: 0, message: "求解服务没有响应，侧车可能已经退出。", messageEn: "The solver service is not responding." }
  assert.equal(classifyLoginError(error), "sidecar")
  const toast = loginToast(error, true, "登录没有成功")
  assert.match(toast.text, /侧车/)
  assert.equal(toast.text.includes("登录没有成功"), false)
})
