import { expect, test } from "@playwright/test"

const themes = ["screen-dark", "screen-light", "publication"] as const
const ground: Record<(typeof themes)[number], string> = {
  "screen-dark": "rgb(20, 22, 26)",
  "screen-light": "rgb(247, 246, 243)",
  publication: "rgb(255, 255, 255)",
}

test("every gallery plate keeps its pixels in three themes", async ({ page }) => {
  await page.goto("/gallery")
  await page.evaluate(() => document.fonts.ready)
  await expect(page.locator("[data-figure-gallery]")).toBeVisible()
  const cards = page.locator("[data-gallery-plate]")
  const count = await cards.count()
  expect(count).toBeGreaterThanOrEqual(18)
  for (const theme of themes) {
    await page.locator(`[data-theme-choice="${theme}"]`).click()
    await page.evaluate(() => document.fonts.ready)
    await expect(page.locator("[data-figure-gallery]")).toHaveCSS("background-color", ground[theme])
    for (let index = 0; index < count; index += 1) {
      const card = cards.nth(index)
      const id = await card.evaluate((node) => {
        const plate = node.querySelector("[data-plate]")
        if (plate?.getAttribute("data-plate")) return plate.getAttribute("data-plate") || "plate"
        if (node.querySelector("[data-sparkline]")) return "sparkline"
        return "plate"
      })
      await expect(card).toHaveScreenshot(`plate-${theme}-${id}.png`, { animations: "disabled" })
      if (theme === "publication") await card.screenshot({ path: `/opt/cursor/artifacts/figures_${id}.png` })
    }
    await expect(page.locator("[data-plate=composer]")).toHaveScreenshot(`plate-${theme}-composer.png`, { animations: "disabled" })
    await page.screenshot({ path: `/opt/cursor/artifacts/figures_gallery_${theme}.png`, fullPage: true })
  }
})
