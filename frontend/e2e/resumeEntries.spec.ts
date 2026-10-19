import { expect, test } from "@playwright/test";
import { expectAccessible } from "./a11y";

test("resume content: collapse, edit, move, undo and save through the real API", async ({
  page,
  request,
}) => {
  const original = await (await request.get("/api/master-resume")).json();
  try {
    await page.goto("/resume");
    const source = page.locator("#resume-section-experience");
    const heading = source.getByRole("button", { name: /^Expand Example Corp/ });
    await expect(heading).toHaveAttribute("aria-expanded", "false");
    await expect(source.getByRole("textbox", { name: "Company", exact: true })).toHaveCount(0);
    const beforeHeight = await source
      .locator("[data-entry-summary]")
      .evaluate((node) => node.getBoundingClientRect().height);
    await heading.click();
    const company = source.getByRole("textbox", { name: "Company", exact: true });
    await company.fill("Example Corp revised");
    await source.getByRole("button", { name: /^Collapse Example Corp revised/ }).click();
    await source.getByRole("button", { name: /^Expand Example Corp revised/ }).click();
    await expect(company).toHaveValue("Example Corp revised");

    await page
      .getByLabel("New section")
      .selectOption({ label: "Research · Labs and research assistant roles" });
    await page.getByRole("button", { name: "Add section" }).click();
    const target = page.locator("#resume-section-research");
    const afterHeight = await source
      .locator("[data-entry-summary]")
      .evaluate((node) => node.getBoundingClientRect().height);
    expect(afterHeight).toBe(beforeHeight);
    const alignment = await source.locator("[data-entry-summary]").evaluate((node) => {
      const row = node.getBoundingClientRect();
      const actions = node.querySelector("[data-entry-actions]")!.getBoundingClientRect();
      return {
        right: row.right - actions.right,
        center: (row.top + row.bottom - actions.top - actions.bottom) / 2,
      };
    });
    expect(Math.abs(alignment.right)).toBeLessThan(1);
    expect(Math.abs(alignment.center)).toBeLessThan(1);
    const handle = source.getByRole("button", { name: /^Drag Example Corp revised/ });
    const controls = await source
      .locator("[data-entry-actions]")
      .evaluate((node) =>
        [...node.querySelectorAll("button")].map(
          (button) => button.getAttribute("aria-label") || button.textContent,
        ),
      );
    expect(controls).toEqual(["Remove", expect.stringMatching(/^Drag Example Corp revised/)]);
    await handle.scrollIntoViewIfNeeded();
    const from = (await handle.boundingBox())!;
    await page.mouse.move(from.x + from.width / 2, from.y + from.height / 2);
    await page.mouse.down();
    // Start the native drag before scrolling to an offscreen destination.
    await page.mouse.move(from.x + from.width / 2 + 12, from.y + from.height / 2 + 12, {
      steps: 3,
    });
    const preview = page.locator("[data-entry-drag-preview]");
    await expect(preview).toHaveCount(1);
    await expect(preview).toContainText("Example Corp revised");
    await expect(preview.locator("input, textarea")).toHaveCount(0);
    await expect(source.locator("[data-resume-entry]")).toHaveClass(/opacity-40/);
    const drop = target.locator("[data-entry-drop-target]");
    await drop.scrollIntoViewIfNeeded();
    const to = (await drop.boundingBox())!;
    await page.mouse.move(to.x + to.width / 2, to.y + to.height / 2, { steps: 5 });
    await page.mouse.up();
    await expect(preview).toHaveCount(0);
    await expect(target.getByRole("textbox", { name: "Company", exact: true })).toHaveValue(
      "Example Corp revised",
    );
    await expect(source.locator("[data-resume-entry]")).toHaveCount(0);
    await page.getByRole("button", { name: "Undo", exact: true }).click();
    await expect(company).toHaveValue("Example Corp revised");
    await expect(target.locator("[data-resume-entry]")).toHaveCount(0);
    await source
      .getByRole("combobox", { name: /^Move Example Corp revised/ })
      .selectOption("research");
    await expectAccessible(page);
    await page.getByRole("button", { name: "Save", exact: true }).click();
    await expect(page.getByText("All changes saved")).toBeVisible();

    const saved = await (await request.get("/api/master-resume")).json();
    const originalJob = original.sections.find((s: { id: string }) => s.id === "experience")
      .entries[0];
    expect(saved.sections.find((s: { id: string }) => s.id === "experience").entries).toEqual([]);
    expect(saved.sections.find((s: { id: string }) => s.id === "research").entries).toEqual([
      { ...originalJob, company: "Example Corp revised" },
    ]);
    await page.reload();
    await expect(
      target.getByRole("button", { name: /^Expand Example Corp revised/ }),
    ).toBeVisible();
  } finally {
    const restored = await request.put("/api/master-resume", { data: original });
    expect(restored.ok()).toBeTruthy();
  }
});

test("dated entries stay chronological through editing, saving and reload, with compact controls", async ({
  page,
  request,
}) => {
  const original = await (await request.get("/api/master-resume")).json();
  const payload = structuredClone(original);
  const jobs = payload.sections.find((s: { id: string }) => s.id === "experience");
  const prototype = jobs.entries[0];
  jobs.entries = [
    {
      ...prototype,
      id: "older",
      company: "Older Company",
      start: "2020-01",
      end: "2021-06",
      bullets: [{ id: "older_b1", text: "Built Python tools.", tags: ["python"] }],
    },
    {
      ...prototype,
      id: "recent",
      company: "Recent Company",
      start: "2023-01",
      end: "2025-06",
      bullets: [{ id: "recent_b1", text: "Built Python tools.", tags: ["python"] }],
    },
    {
      ...prototype,
      id: "current",
      company: "Current Company",
      start: "2024-01",
      end: "Present",
      bullets: [{ id: "current_b1", text: "Built Python tools.", tags: ["python"] }],
    },
  ];
  payload.sections.push({ id: "research", kind: "experience", title: "Research", entries: [] });
  payload.sections.push({
    id: "certs",
    kind: "list",
    title: "Certifications",
    entries: [
      { id: "cert", text: "A long certification entry with enough words to wrap on a phone" },
    ],
  });
  payload.sections.push({ id: "awards", kind: "list", title: "Awards", entries: [] });
  try {
    expect((await request.put("/api/master-resume", { data: payload })).ok()).toBeTruthy();
    await page.goto("/resume");
    const source = page.locator("#resume-section-experience");
    const titles = source.locator("[data-entry-summary] > div:first-child > button");
    await expect(titles).toHaveText([/Current Company/, /Recent Company/, /Older Company/]);
    await expect(
      source.locator("[data-entry-actions]").getByRole("button", { name: "Move up" }),
    ).toHaveCount(0);
    await source.getByRole("button", { name: /^Expand Older Company/ }).click();
    const endYear = source.getByRole("textbox", { name: "End, year" });
    await endYear.fill("2028");
    await expect(titles).toHaveText([/Current Company/, /Recent Company/, /Older Company/]);
    await expect(endYear).toBeFocused();
    await source.getByRole("button", { name: /^Collapse Older Company/ }).click();
    await expect(titles).toHaveText([/Current Company/, /Older Company/, /Recent Company/]);
    await page.getByRole("button", { name: "Save", exact: true }).click();
    await expect(page.getByText("All changes saved")).toBeVisible();
    const saved = await (await request.get("/api/master-resume")).json();
    expect(
      saved.sections
        .find((s: { id: string }) => s.id === "experience")
        .entries.map((e: { id: string }) => e.id),
    ).toEqual(["current", "older", "recent"]);
    await page.reload();
    await expect(titles).toHaveText([/Current Company/, /Older Company/, /Recent Company/]);
    await page.setViewportSize({ width: 375, height: 812 });
    for (const actions of await page.locator("[data-entry-actions]").all()) {
      const bounds = await actions.boundingBox();
      expect(bounds!.x).toBeGreaterThanOrEqual(0);
      expect(bounds!.x + bounds!.width).toBeLessThanOrEqual(375);
    }
    await expect(
      page
        .locator("#resume-section-certs [data-entry-actions]")
        .getByRole("button", { name: "Move up" }),
    ).toHaveCount(1);
    await page.screenshot({ path: "test-results/resume-entries-mobile.png", fullPage: true });
    await page.setViewportSize({ width: 1280, height: 900 });
    await page.screenshot({ path: "test-results/resume-entries-desktop.png", fullPage: true });
  } finally {
    expect((await request.put("/api/master-resume", { data: original })).ok()).toBeTruthy();
  }
});
