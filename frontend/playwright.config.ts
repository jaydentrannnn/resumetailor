import { defineConfig, devices } from "@playwright/test";

// Browser end-to-end suite. Runs the real app against a throwaway server with the
// canned fake model (`scripts/e2e_server.py`); build the SPA first (`npm run e2e` does).
// PW_CHROMIUM_PATH points at an already-installed Chromium instead of Playwright's own.
const port = Number(process.env.E2E_PORT ?? 8777);
const python = process.env.E2E_PYTHON ?? "../.venv/bin/python";

export default defineConfig({
  testDir: "./e2e",
  timeout: 120_000,
  expect: { timeout: 15_000 },
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: [["list"]],
  use: {
    baseURL: `http://127.0.0.1:${port}`,
    trace: "retain-on-failure",
    launchOptions: process.env.PW_CHROMIUM_PATH
      ? { executablePath: process.env.PW_CHROMIUM_PATH }
      : {},
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: {
    command: `${python} ../scripts/e2e_server.py --port ${port}`,
    // The last seeded application: 404 until seeding has finished.
    url: `http://127.0.0.1:${port}/api/applications/e2e-queued`,
    timeout: 240_000,
    reuseExistingServer: false,
    stdout: "pipe",
  },
});
