import fs from "node:fs"
import path from "node:path"
import { fileURLToPath } from "node:url"
import { defineConfig, devices } from "@playwright/test"

const root = path.dirname(fileURLToPath(import.meta.url))
const backend = path.resolve(root, "../backend")
const venvPython = path.join(backend, ".venv", "bin", "python")
const python = fs.existsSync(venvPython) ? venvPython : "python"

export default defineConfig({
  testDir: "./e2e",
  timeout: 180_000,
  expect: { timeout: 20_000 },
  fullyParallel: false,
  workers: 1,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [["github"], ["list"]] : "list",
  use: {
    baseURL: "http://127.0.0.1:43123",
    viewport: { width: 1440, height: 900 },
    trace: "retain-on-failure",
  },
  projects: [
    {
      name: "chromium",
      testIgnore: /figures\.spec\.ts/,
      use: {
        ...devices["Desktop Chrome"],
        channel: process.env.CI ? undefined : "chrome",
      },
    },
    {
      name: "figures",
      testMatch: /figures\.spec\.ts/,
      use: {
        ...devices["Desktop Chrome"],
        viewport: { width: 1280, height: 900 },
      },
    },
  ],
  webServer: [
    {
      command: `"${python}" -m uvicorn axiom.main:app --host 127.0.0.1 --port 43124`,
      cwd: backend,
      url: "http://127.0.0.1:43124/api/health",
      reuseExistingServer: !process.env.CI,
      timeout: 120_000,
      env: {
        ...process.env,
        PYTHONPATH: backend,
        AXIOM_SKIP_EXAMPLE: "1",
        AXIOM_DATA_DIR: path.join(backend, ".e2e-data"),
      },
    },
    {
      command: "npm run dev -- --host 127.0.0.1 --port 43123 --strictPort",
      url: "http://127.0.0.1:43123",
      reuseExistingServer: !process.env.CI,
      timeout: 120_000,
    },
  ],
})
