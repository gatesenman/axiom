import { expect, test } from "@playwright/test"
import { login } from "./studio"

const PRODUCT = [
  "model ProductMix;",
  "var xA >= 0;",
  "var xB >= 0;",
  "maximize profit: 40 * xA + 30 * xB;",
  "subject to labor: 2 * xA + 3 * xB <= 120;",
  "subject to material: 3 * xA + xB <= 90;",
].join("\n")

const INFEASIBLE = ["var x >= 0;", "maximize obj: x;", "subject to low: x >= 5;", "subject to high: x <= 3;"].join("\n")

test("import wizard writes a table into the model", async ({ page }) => {
  const token = await login(page)
  const created = await page.request.post("/api/projects", {
    headers: { Authorization: `Bearer ${token}` },
    data: { title: "导入", dsl: PRODUCT, statement: "导入产能", locale: "zh-CN" },
  })
  const project = (await created.json()) as { id: number }
  await page.goto(`/projects/${project.id}`)
  await page.locator('input[accept=".csv,.xlsx,.xlsm"]').setInputFiles({
    name: "plants.csv",
    mimeType: "text/csv",
    buffer: Buffer.from("plant,capacity\nNorth,10\nSouth,12\n"),
  })
  await expect(page.locator("[data-wizard=import]")).toBeVisible()
  await expect(page.locator("[data-wizard=import]")).toContainText("North")
  await page.getByRole("button", { name: "写入模型" }).click()
  await page.getByRole("tab", { name: "模型" }).click()
  await expect(page.locator(".cm-content")).toContainText("North")
})

test("parameter grid edits a right-hand side and undo restores it", async ({ page }) => {
  const token = await login(page)
  const created = await page.request.post("/api/projects", {
    headers: { Authorization: `Bearer ${token}` },
    data: { title: "参数表", dsl: PRODUCT, statement: "工时", locale: "zh-CN" },
  })
  const project = (await created.json()) as { id: number }
  await page.goto(`/projects/${project.id}`)
  await page.getByRole("tab", { name: "数据" }).click()
  const labor = page.locator("[data-rhs=labor]")
  await expect(labor).toHaveValue("120")
  await labor.fill("100")
  await labor.press("Enter")
  await page.getByRole("tab", { name: "模型" }).click()
  await expect(page.locator(".cm-content")).toContainText("<= 100")
  await page.keyboard.press("Control+z")
  await expect(page.locator(".cm-content")).toContainText("<= 120")
})

test("an infeasible solve explains the conflict and jumps to the equation", async ({ page }) => {
  const token = await login(page)
  const headers = { Authorization: `Bearer ${token}` }
  const created = await page.request.post("/api/projects", {
    headers,
    data: { title: "不可行", dsl: INFEASIBLE, statement: "上下界冲突", locale: "zh-CN" },
  })
  const project = (await created.json()) as { id: number }
  const started = await page.request.post(`/api/projects/${project.id}/runs`, {
    headers,
    data: { dsl: INFEASIBLE, statement: "上下界冲突", solver: "highs", auto_approve: true },
  })
  const runId = ((await started.json()) as { id: number }).id
  await expect.poll(async () => {
    const current = await page.request.get(`/api/runs/${runId}`, { headers })
    return ((await current.json()) as { status: string }).status
  }, { timeout: 60_000 }).toBe("completed")
  await page.goto(`/projects/${project.id}`)
  await page.getByRole("tab", { name: "结果" }).click()
  await expect(page.getByText("冲突").first()).toBeVisible()
  const diagnosis = page.locator("[data-diagnosis]").first()
  await expect(diagnosis).toContainText("放松")
  await diagnosis.click()
  await expect(page.locator("[data-equations=ready]")).toBeVisible()
  await expect(page.locator('[data-active="true"]').first()).toBeVisible()
})

test("status bar shows solve progress and the restore dialog offers the draft", async ({ page }) => {
  const token = await login(page)
  const created = await page.request.post("/api/projects", {
    headers: { Authorization: `Bearer ${token}` },
    data: { title: "进度", dsl: PRODUCT, statement: "等待批准", locale: "zh-CN" },
  })
  const project = (await created.json()) as { id: number }
  await page.goto(`/projects/${project.id}`)
  await page.getByRole("button", { name: "开始求解" }).click()
  await expect(page.locator("footer [data-solve-progress]")).toContainText("求解")
  await page.evaluate((projectId) => {
    localStorage.setItem("axiom.recovery", JSON.stringify({
      projectId,
      title: "恢复标题",
      statement: "草稿正文",
      dsl: "var z >= 0;\nmaximize obj: z;\n",
      auto: false,
      solver: "highs",
      savedAt: new Date().toISOString(),
    }))
  }, project.id)
  await page.reload()
  await expect(page.locator("[data-restore]")).toBeVisible()
  await page.getByRole("button", { name: "恢复" }).click()
  await expect(page.locator("input").first()).toHaveValue("恢复标题")
})

test("what-if, versions, recommendation, gallery, and package", async ({ page }) => {
  const token = await login(page)
  const headers = { Authorization: `Bearer ${token}` }
  const created = await page.request.post("/api/projects", {
    headers,
    data: { title: "对照", dsl: PRODUCT, statement: "对照基准", locale: "zh-CN" },
  })
  const project = (await created.json()) as { id: number }
  await page.request.post(`/api/projects/${project.id}/versions`, {
    headers,
    data: { label: "旧稿", dsl: "var z >= 0;\nmaximize obj: z;\n", statement: "旧" },
  })
  await page.goto(`/projects/${project.id}`)
  await expect(page.locator("[data-recommend]")).toContainText("单纯形")
  await page.getByRole("combobox").first().click()
  await page.getByRole("option", { name: "CBC" }).click()
  await page.getByRole("button", { name: "采用建议" }).click()
  await expect(page.getByRole("combobox").first()).toContainText("HiGHS")

  await page.getByRole("tab", { name: "结果" }).click()
  const labor = page.locator("[data-whatif-value=labor]")
  await expect(labor).toBeVisible()
  await labor.fill("200")
  await page.getByRole("button", { name: "重算" }).click()
  await expect(page.locator("[data-whatif-scenario]")).toBeVisible()
  await expect(page.locator("[data-chart=whatif]")).toBeVisible()

  await page.locator("[data-versions]").getByText("旧稿").locator("xpath=..").getByRole("button", { name: "回滚" }).click()
  await expect(page.locator(".cm-content")).toContainText("var z")

  await page.getByRole("button", { name: "文件" }).click()
  await page.getByRole("menuitem", { name: "行业模板" }).click()
  await expect(page.locator("[data-gallery]")).toContainText("运输")
  await expect(page.locator("[data-gallery]")).toContainText("排班")
  await page.keyboard.press("Escape")
  await page.getByRole("button", { name: "保存", exact: true }).click()
  await expect(page.getByText("已保存").first()).toBeVisible()

  const started = await page.request.post(`/api/projects/${project.id}/runs`, {
    headers,
    data: { dsl: PRODUCT, statement: "对照基准", solver: "highs", auto_approve: true },
  })
  const runId = ((await started.json()) as { id: number }).id
  await expect.poll(async () => {
    const current = await page.request.get(`/api/runs/${runId}`, { headers })
    return ((await current.json()) as { status: string }).status
  }, { timeout: 90_000 }).toBe("completed")
  await page.goto(`/projects/${project.id}`)
  await page.getByRole("tab", { name: "结果" }).click()
  const downloadPromise = page.waitForEvent("download")
  await page.getByRole("button", { name: "打包分享" }).click()
  const download = await downloadPromise
  expect(download.suggestedFilename()).toContain("axiom-package.zip")
})
