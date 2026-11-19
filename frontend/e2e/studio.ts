import { expect, type Page } from "@playwright/test"

export const PRODUCT_STATEMENT = [
  "一家工厂生产产品A和产品B。产品A单位利润40元，产品B单位利润30元。",
  "生产一件A需要2小时机器时间和3公斤原料，生产一件B需要3小时机器时间和1公斤原料。",
  "每周机器时间不超过120小时，原料不超过90公斤。请制定利润最大的生产计划。",
].join("")

export async function login(page: Page): Promise<string> {
  await page.goto("/login")
  await page.locator("#username").fill("demo")
  await page.locator("#password").fill("demo1234")
  await page.locator('form button[type="submit"]').click()
  await expect(page.getByRole("button", { name: /^(文件|File)$/ })).toBeVisible()
  const token = await page.evaluate(() => localStorage.getItem("axiom_token"))
  if (!token) throw new Error("login did not store a token")
  const me = await page.request.patch("/api/auth/me", {
    headers: { Authorization: `Bearer ${token}` },
    data: { locale: "zh-CN", theme: "dark" },
  })
  expect(me.ok()).toBeTruthy()
  await page.evaluate(() => {
    localStorage.setItem("axiom_locale", "zh-CN")
    localStorage.setItem("theme", "dark")
  })
  await page.reload()
  await expect(page.getByRole("button", { name: "文件" })).toBeVisible()
  return token
}

type RunPayload = {
  id: number
  project_id: number
  status: string
  objective: string
  result: {
    objective?: number
    variables?: Record<string, number>
    scenarios?: { name: string; objective: number | null }[]
    sensitivity?: { rows?: { name: string; span: number; low: number; high: number; base: number }[] }
  }
}

export async function productRun(page: Page, token: string): Promise<RunPayload> {
  const headers = { Authorization: `Bearer ${token}` }
  const listed = await page.request.get("/api/projects", { headers })
  expect(listed.ok()).toBeTruthy()
  const projects = (await listed.json()) as { id: number; title: string; statement: string }[]
  for (const project of projects) {
    const related = (project.statement || "").includes("产品A")
    if (!related) continue
    const runsResponse = await page.request.get(`/api/projects/${project.id}/runs`, { headers })
    const runs = (await runsResponse.json()) as RunPayload[]
    const done = runs.find((run) => run.status === "completed" && Math.abs(Number(run.result?.objective ?? run.objective) - 1628.57) < 2)
    if (done) return done
  }

  const created = await page.request.post("/api/projects", {
    headers,
    data: { title: "图表校验", statement: PRODUCT_STATEMENT, locale: "zh-CN" },
  })
  expect(created.ok()).toBeTruthy()
  const project = (await created.json()) as { id: number }
  const started = await page.request.post(`/api/projects/${project.id}/runs`, {
    headers,
    data: { statement: PRODUCT_STATEMENT, dsl: "", auto_approve: true, solver: "highs" },
  })
  expect(started.ok()).toBeTruthy()
  const runId = ((await started.json()) as { id: number }).id
  let payload = {} as RunPayload
  await expect
    .poll(
      async () => {
        const current = await page.request.get(`/api/runs/${runId}`, { headers })
        payload = (await current.json()) as RunPayload
        return payload.status
      },
      { timeout: 150_000, intervals: [1_000] },
    )
    .toBe("completed")
  return payload
}

export async function decodeVerticalBars(page: Page, chart: string) {
  return page.locator(`[data-chart="${chart}"]`).evaluate((root) => {
    const parse = (text: string) => Number(text.replace(/,/g, "").replace(/\s/g, "").replace(/−/g, "-"))
    const ticks = [...root.querySelectorAll(".recharts-yAxis-tick-labels text")]
      .map((node) => {
        const box = node.getBoundingClientRect()
        return { value: parse(node.textContent || ""), y: box.top + box.height / 2 }
      })
      .filter((tick) => Number.isFinite(tick.value))
      .sort((a, b) => a.y - b.y)
    const labels = [...root.querySelectorAll(".recharts-xAxis-tick-labels text")].map((node) => (node.textContent || "").trim())
    const hi = ticks[0]
    const lo = ticks[ticks.length - 1]
    const bars = [...root.querySelectorAll(".recharts-bar-rectangle")].map((node) => {
      const box = node.getBoundingClientRect()
      const value = hi && lo && hi.y !== lo.y ? lo.value + ((lo.y - box.top) / (lo.y - hi.y)) * (hi.value - lo.value) : Number.NaN
      return { height: box.height, value }
    })
    return { labels, ticks, bars }
  })
}

export async function decodeHorizontalBars(page: Page, chart: string) {
  return page.locator(`[data-chart="${chart}"]`).evaluate((root) => {
    const parse = (text: string) => Number(text.replace(/,/g, "").replace(/\s/g, "").replace(/−/g, "-"))
    const ticks = [...root.querySelectorAll(".recharts-xAxis-tick-labels text")]
      .map((node) => {
        const box = node.getBoundingClientRect()
        return { value: parse(node.textContent || ""), x: box.left + box.width / 2 }
      })
      .filter((tick) => Number.isFinite(tick.value))
      .sort((a, b) => a.x - b.x)
    const labels = [...root.querySelectorAll(".recharts-yAxis-tick-labels text")].map((node) => (node.textContent || "").trim())
    const lo = ticks[0]
    const hi = ticks[ticks.length - 1]
    const bars = [...root.querySelectorAll(".recharts-bar-rectangle")].map((node) => {
      const box = node.getBoundingClientRect()
      const value = hi && lo && hi.x !== lo.x ? lo.value + ((box.right - lo.x) / (hi.x - lo.x)) * (hi.value - lo.value) : Number.NaN
      return { height: box.height, width: box.width, value }
    })
    return { labels, ticks, bars }
  })
}
