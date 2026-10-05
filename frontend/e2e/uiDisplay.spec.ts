import { expect, test } from "@playwright/test";
import type { ApplyOperation } from "../src/api";

test("Find jobs advances through source and posting stages with newest activity first", async ({
  page,
}) => {
  let started = false;
  let snapshot: ApplyOperation = {
    operation_id: "display-test",
    action: "find",
    state: "running",
    application_ids: [],
    current_application_id: "",
    current_label: "",
    stage: "discovering",
    message: "Fetching sources",
    processed: 0,
    total: 1,
    completed: 0,
    blocked: 0,
    failed: 0,
    submitted: 0,
    started_at: new Date().toISOString(),
    updated_at: "",
    heartbeat_at: "",
    current_step: 0,
    application_started_at: "",
    finished_at: "",
    effective_model: "fake",
    auto_submit: false,
    blocker_mode: "continue",
    events: [
      { at: "2026-01-01T00:00:00Z", message: "Search started" },
      { at: "2026-01-01T00:00:01Z", message: "Source finished" },
    ],
    find_progress: { phase: "discovering", processed: 2, total: 4, current: "Internships" },
  };
  await page.route("**/api/applications/operations", async (route) => {
    if (route.request().method() === "POST") {
      expect(route.request().postDataJSON().action).toBe("find");
      started = true;
      await route.fulfill({ json: snapshot });
    } else {
      await route.fulfill({ json: started ? [snapshot] : [] });
    }
  });
  await page.route("**/api/applications/operations/display-test", (route) =>
    route.fulfill({ json: snapshot }),
  );
  await page.goto("/applications?tab=progress");
  await page.getByRole("button", { name: "Find jobs", exact: true }).click();
  const bar = page.getByRole("progressbar", { name: "Find jobs progress" });
  await expect(bar).toHaveAttribute("aria-valuenow", "25");
  await expect(bar).toHaveAttribute("aria-valuetext", "Fetching sources: 2 of 4 · Internships");
  await page.getByText("Activity", { exact: true }).click();
  const activities = page.getByText("Activity", { exact: true }).locator("..").locator("ul li");
  await expect(activities.first()).toContainText("Source finished");
  await expect(activities.last()).toContainText("Search started");

  snapshot = {
    ...snapshot,
    find_progress: { phase: "processing", processed: 0, total: 20, current: "" },
  };
  await expect(bar).toHaveAttribute("aria-valuenow", "50");
  snapshot = {
    ...snapshot,
    find_progress: { phase: "processing", processed: 8, total: 20, current: "Acme" },
  };
  await expect(bar).toHaveAttribute("aria-valuenow", "70");
  await expect(bar).toHaveAttribute("aria-valuetext", "Processing postings: 8 of 20 · Acme");
  snapshot = {
    ...snapshot,
    state: "completed",
    find_progress: { phase: "processing", processed: 20, total: 20, current: "" },
  };
  await expect(bar).toHaveAttribute("aria-valuenow", "100");
});

for (const touch of [false, true]) {
  test.describe(touch ? "touch controls" : "desktop controls", () => {
    test.use({ viewport: { width: 1280, height: 900 }, hasTouch: touch });

    test("model fields align and header pills have equal heights", async ({ page }) => {
      await page.route("**/api/update", (route) =>
        route.fulfill({
          json: {
            supported: true,
            current: "0.1.1",
            state: "available",
            available: { version: "0.2.0", notes: "Update", date: "" },
            pct: null,
            last_checked: null,
            error: null,
            waiting_for: null,
            backup: null,
          },
        }),
      );
      await page.route("**/api/setup-status", (route) =>
        route.fulfill({
          json: { items: [], ready: true, remaining: 0 },
        }),
      );
      await page.route("**/api/automation", (route) =>
        route.fulfill({
          json: { paused: false, changed_at: "", auto_submits_24h: 0, max_per_day: 0 },
        }),
      );
      await page.route("**/api/models/local?*", (route) =>
        route.fulfill({
          json: { reachable: false, models: [] },
        }),
      );
      await page.goto("/settings?tab=models");
      const model = page.locator(".rt-model-label").first().locator("..").locator("input");
      const effort = page.locator(".rt-model-label").nth(1).locator("..").locator("select");
      await expect(model).toBeVisible();
      await expect(effort).toBeVisible();
      const modelBox = (await model.boundingBox())!;
      const effortBox = (await effort.boundingBox())!;
      expect(Math.abs(modelBox.y - effortBox.y)).toBeLessThan(1);
      expect(Math.abs(modelBox.height - effortBox.height)).toBeLessThan(1);

      const pills = [
        page.getByRole("button", { name: "Ready", exact: true }),
        page.getByRole("link", { name: "Update available" }),
        page.getByRole("button", { name: "Pause automation", exact: true }),
      ];
      const heights = [];
      for (const pill of pills) {
        await expect(pill).toBeVisible();
        heights.push((await pill.boundingBox())!.height);
      }
      expect(heights).toEqual([touch ? 44 : 36, touch ? 44 : 36, touch ? 44 : 36]);
      const fonts = [];
      for (const pill of pills) {
        fonts.push(
          await pill.evaluate((element) => {
            const style = getComputedStyle(element);
            return [style.fontSize, style.lineHeight, style.fontWeight];
          }),
        );
      }
      expect(fonts[1]).toEqual(fonts[0]);
      expect(fonts[2]).toEqual(fonts[0]);
      expect(fonts[0]).toEqual(["12px", "16px", "600"]);

      const help = page.getByRole("button", { name: "What is effort?" });
      await help.click();
      await expect(page.getByRole("note")).toBeVisible();
      await page.keyboard.press("Escape");
      await expect(page.getByRole("note")).toHaveCount(0);

      await page.setViewportSize({ width: 390, height: 844 });
      await expect(model).toBeVisible();
      await expect(effort).toBeVisible();
      expect((await effort.boundingBox())!.y).toBeGreaterThan((await model.boundingBox())!.y);
      expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(
        390,
      );
    });
  });
}
