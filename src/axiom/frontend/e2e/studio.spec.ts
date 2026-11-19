import { expect, test } from "@playwright/test"
import { decodeHorizontalBars, decodeVerticalBars, login, productRun } from "./studio"

test("studio pages, language, and mobile menu", async ({ page }) => {
  await login(page)
  await expect(page.getByRole("button", { name: "文件" })).toBeVisible()
  await expect(page.locator("[data-screen=welcome]")).toBeVisible()
  await expect(page.locator("[data-tour=start]")).toBeVisible()
  await page.getByRole("button", { name: "跳过" }).click()
  await expect(page.locator("[data-tour=start]")).toHaveCount(0)
  await expect(page.locator("[data-status-lang]")).toHaveText("中文")
  await expect(page.getByRole("button", { name: "求解", exact: true })).toBeVisible()
  await expect(page.getByRole("button", { name: "开始求解" })).toBeVisible()
  await expect(page.locator('[data-panel="explorer"]')).toBeVisible()

  await page.getByRole("button", { name: "模板" }).click()
  await expect(page.locator('[data-panel="explorer"]')).toContainText("模板库")
  await expect(page.getByText("单机调度")).toBeVisible()

  await page.getByRole("button", { name: "工具" }).click()
  await page.getByRole("menuitem", { name: "工作区" }).click()
  await expect(page.getByRole("heading", { name: "工作区与成员" })).toBeVisible()
  await page.keyboard.press("Escape")

  await page.getByRole("button", { name: "工具" }).click()
  await page.getByRole("menuitem", { name: "审计" }).click()
  await expect(page.getByRole("heading", { name: "审计日志" })).toBeVisible()
  await page.keyboard.press("Escape")

  await page.getByRole("button", { name: "编辑" }).click()
  await page.getByRole("menuitem", { name: "命令面板" }).click()
  await expect(page.getByPlaceholder("命令面板")).toBeVisible()
  await expect(page.getByText("Start solve")).toBeVisible()
  await page.keyboard.press("Escape")
  await page.evaluate(() => {
    window.dispatchEvent(new KeyboardEvent("keydown", { key: "p", ctrlKey: true, shiftKey: true, bubbles: true, cancelable: true }))
  })
  await expect(page.getByPlaceholder("命令面板")).toBeVisible()
  await page.keyboard.press("Escape")

  await page.getByRole("button", { name: "设置", exact: true }).click()
  await expect(page.getByRole("heading", { name: "设置" })).toBeVisible()
  await expect(page.getByRole("row").filter({ has: page.getByText("HiGHS", { exact: true }) }).getByText("可用")).toBeVisible()

  await page.getByRole("button", { name: "English" }).click()
  await expect(page.getByRole("heading", { name: "Settings" })).toBeVisible()
  await page.keyboard.press("Escape")
  await expect(page.getByRole("button", { name: "File" })).toBeVisible()
  await expect(page.locator("[data-status-lang]")).toHaveText("EN")
  await page.getByRole("button", { name: "中文", exact: true }).click()
  await expect(page.locator("[data-status-lang]")).toHaveText("中文")
  await expect(page.getByRole("button", { name: "文件" })).toBeVisible()

  await page.setViewportSize({ width: 390, height: 844 })
  await page.reload()
  await expect(page.locator('[data-panel="explorer"]')).toHaveCount(0)
  await page.getByRole("button", { name: "menu" }).click()
  await expect(page.locator('[data-panel="explorer"]')).toBeVisible()
  await expect(page.getByRole("button", { name: "模板" })).toBeVisible()
})

test("editor keeps an unsaved mark and jumps from the problems list", async ({ page }) => {
  const token = await login(page)
  const created = await page.request.post("/api/projects", {
    headers: { Authorization: `Bearer ${token}` },
    data: { title: "诊断校验", statement: "空集合", dsl: "var x >= 0;\n", locale: "zh-CN" },
  })
  expect(created.ok()).toBeTruthy()
  const project = (await created.json()) as { id: number }
  await page.goto(`/projects/${project.id}`)
  await page.getByRole("tab", { name: "模型" }).click()
  await expect(page.locator(".cm-editor")).toBeVisible()
  await page.locator(".cm-content").click()
  await page.keyboard.press("Control+End")
  await page.keyboard.type("set S := ;\n")
  await expect(page.locator("[data-unsaved=problem]")).toBeVisible()
  await page.locator("button.app-menu", { hasText: "模型" }).click()
  await page.getByRole("menuitem", { name: "校验模型" }).click()
  const problem = page.locator("[data-panel=problems] button").first()
  await expect(problem).toBeVisible()
  await problem.click()
  await expect(page.locator(".cm-editor")).toBeVisible()
  await expect(page.locator(".cm-lintRange-error, .cm-lint-marker-error").first()).toBeVisible()
})

test("result charts match the solved numbers as soon as they paint", async ({ page }) => {
  const token = await login(page)
  const run = await productRun(page, token)
  const variables = Object.entries(run.result.variables || {}).filter(([name]) => !name.startsWith("_") && !name.startsWith("s_"))
  const scenarios = (run.result.scenarios || []).filter((row) => row.objective !== null)
  const sensitivity = run.result.sensitivity?.rows || []
  expect(variables.map(([name]) => name)).toEqual(["x_A", "x_B"])
  expect(Number(run.result.objective)).toBeGreaterThan(1000)

  await page.goto(`/projects/${run.project_id}`)
  await page.getByRole("tab", { name: "模型" }).click()
  await expect(page.locator(".cm-editor")).toBeVisible()
  await page.getByRole("tab", { name: "智能体日志" }).click()
  await expect(page.getByText("分析", { exact: false }).first()).toBeVisible()
  await page.getByRole("tab", { name: "导出" }).click()
  await page.getByRole("tab", { name: "结果" }).click()
  await expect(page.locator("[data-decision]")).toBeVisible()

  await page.locator('[data-chart="variables"] .recharts-bar-rectangle').first().waitFor({ state: "attached" })
  let variablesChart = await decodeVerticalBars(page, "variables")
  if (variablesChart.bars.every((bar) => bar.height < 2)) {
    await page.evaluate(() => new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(() => resolve(undefined)))))
    variablesChart = await decodeVerticalBars(page, "variables")
  }

  const tableNames = (await page.locator('[data-chart="variable-table"] tbody tr td:first-child').allTextContents()).map((text) => text.trim())
  expect(variablesChart.labels).toEqual(tableNames.slice(0, variablesChart.labels.length))
  expect(variablesChart.labels).toEqual(variables.map(([name]) => name))
  expect(variablesChart.bars).toHaveLength(variables.length)
  variables.forEach(([, value], index) => {
    const decoded = variablesChart.bars[index].value
    expect(Math.abs(decoded - value) / Math.abs(value)).toBeLessThan(0.12)
    expect(variablesChart.bars[index].height).toBeGreaterThan(40)
  })
  expect(variablesChart.bars[1].height / variablesChart.bars[0].height).toBeGreaterThan(1.1)
  expect(variablesChart.bars[1].height / variablesChart.bars[0].height).toBeLessThan(1.35)

  const scenarioChart = await decodeVerticalBars(page, "scenarios")
  expect(scenarioChart.labels).toEqual(scenarios.map((row) => row.name))
  scenarios.forEach((row, index) => {
    const decoded = scenarioChart.bars[index].value
    expect(decoded).toBeGreaterThan(1000)
    expect(Math.abs(decoded - Number(row.objective)) / Number(row.objective)).toBeLessThan(0.12)
  })
  expect(scenarioChart.bars[1].height).toBeGreaterThan(scenarioChart.bars[0].height)
  expect(scenarioChart.bars[0].height).toBeGreaterThan(scenarioChart.bars[2].height)

  await expect(page.getByText("横条是目标值在 ±10% 扰动下的跨度")).toBeVisible()
  const sensitivityChart = await decodeHorizontalBars(page, "sensitivity")
  expect(sensitivityChart.ticks.length).toBeGreaterThanOrEqual(2)
  expect(sensitivityChart.labels.filter(Boolean).length).toBeGreaterThan(0)
  const tickValues = sensitivityChart.ticks.map((tick) => tick.value)
  const maxTick = Math.max(...tickValues)
  expect(maxTick).toBeGreaterThan(10)
  expect(maxTick).toBeLessThan(Number(run.result.objective) / 2)
  sensitivity.forEach((row, index) => {
    expect(Math.abs(sensitivityChart.bars[index].value - row.span) / Math.max(row.span, 1)).toBeLessThan(0.2)
  })
})
