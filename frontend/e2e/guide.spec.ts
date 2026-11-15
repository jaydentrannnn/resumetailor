import { expect, test, type Page } from "@playwright/test";
import type { ApplyOperation, RunHistoryEntry } from "../src/api";

const emptyProgress = {
  found: 0,
  screened_in: 0,
  tailored: 0,
  autofilled: 0,
  sent: [],
  sent_total: 0,
  needs_you: 0,
  ready: 0,
  unscreened: 0,
  postings: [],
};
const run = (status: RunHistoryEntry["status"]): RunHistoryEntry => ({
  job_id: "guide-run",
  status,
  created_at: "2026-01-01T00:00:00Z",
  finished_at: "2026-01-01T00:01:00Z",
  title: "Test posting",
  error: null,
  pages: null,
  coverage_matched: null,
  coverage_total: null,
  has_pdf: status === "succeeded",
  has_docx: status === "succeeded",
});

async function showGuide(page: Page, status: RunHistoryEntry["status"]) {
  await page.route("**/api/onboarding", (route) =>
    route.fulfill({
      json: {
        step: "done",
        completed: true,
        skipped: false,
        apply_done: true,
        guide_dismissed: false,
      },
    }),
  );
  await page.route("**/api/setup-status", (route) =>
    route.fulfill({ json: { items: [], ready: true, remaining: 0 } }),
  );
  await page.route("**/api/jobs", (route) => route.fulfill({ json: { runs: [run(status)] } }));
  await page.route("**/api/applications/progress", (route) =>
    route.fulfill({ json: emptyProgress }),
  );
}

test("a failed first run leaves Tailor your first resume as the next guide step", async ({
  page,
}) => {
  await showGuide(page, "failed");
  await page.goto("/");
  const guide = page.getByRole("region", { name: "Getting started", exact: true });
  await expect(guide.locator('li[aria-current="step"]')).toContainText("Tailor your first resume");
});

test("Find jobs advances the rail guide without leaving Apply", async ({ page }) => {
  await showGuide(page, "succeeded");
  let started = false;
  const operation: ApplyOperation = {
    operation_id: "guide-find",
    action: "find",
    state: "completed",
    application_ids: [],
    current_application_id: "",
    current_label: "",
    stage: "completed",
    message: "Search complete",
    processed: 1,
    total: 1,
    completed: 1,
    blocked: 0,
    failed: 0,
    submitted: 0,
    started_at: "2026-01-01T00:00:00Z",
    updated_at: "",
    heartbeat_at: "",
    current_step: 0,
    application_started_at: "",
    finished_at: "2026-01-01T00:01:00Z",
    effective_model: "fake",
    auto_submit: false,
    blocker_mode: "continue",
    events: [],
    find_progress: { phase: "processing", processed: 1, total: 1, current: "" },
  };
  await page.route("**/api/applications/progress", (route) =>
    route.fulfill({ json: { ...emptyProgress, found: started ? 1 : 0 } }),
  );
  await page.route("**/api/applications/operations", (route) => {
    if (route.request().method() === "POST") {
      expect(route.request().postDataJSON().action).toBe("find");
      started = true;
      return route.fulfill({ json: operation });
    }
    return route.fulfill({ json: started ? [operation] : [] });
  });
  await page.route("**/api/applications/operations/guide-find", (route) =>
    route.fulfill({ json: operation }),
  );
  await page.goto("/applications?tab=progress");
  const pill = page.getByRole("button", { name: /^Getting started: \d of 6 steps done$/ });
  await pill.click();
  const panel = page.locator(`#${await pill.getAttribute("aria-controls")}`);
  await expect(panel.locator('li[aria-current="step"]')).toContainText("Find jobs");
  await pill.click();
  await page.getByRole("button", { name: "Find jobs", exact: true }).click();
  await expect.poll(() => started).toBe(true);
  await pill.click();
  await expect(panel.locator('li[aria-current="step"]')).toContainText(
    "Fill your first application",
  );
  await expect(page).toHaveURL(/\/applications\?tab=progress$/);
});

test("the nightly guide link opens settings from Apply and Back closes it", async ({ page }) => {
  await showGuide(page, "succeeded");
  await page.route("**/api/applications/progress", (route) =>
    route.fulfill({ json: { ...emptyProgress, found: 1, autofilled: 1 } }),
  );
  await page.goto("/applications?tab=progress");
  await page.getByRole("button", { name: /^Getting started:/ }).click();
  await page.getByRole("link", { name: "Turn on the nightly run", exact: true }).click();
  const drawer = page.getByRole("dialog", { name: "Apply settings", exact: true });
  await expect(drawer.getByRole("heading", { name: "Nightly run", exact: true })).toBeVisible();
  await page.goBack();
  await expect(drawer).toBeHidden();
});
