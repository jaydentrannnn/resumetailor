import { expect, test } from "@playwright/test";
import { expectAccessible } from "./a11y";

const JD = `Data Analyst Intern
We are hiring a data analyst intern. You will use Python and SQL to build dashboards,
work with stakeholders, and present findings. Experience with search and ranking helps.`;

test("tailor a resume, edit a bullet and re-render without AI", async ({ page }) => {
  await page.goto("/");
  await page.getByLabel("Job description text").fill(JD);
  await page.getByRole("button", { name: "Tailor resume" }).click();
  await expect(page.getByRole("tab", { name: "Review bullets" })).toBeVisible({ timeout: 90_000 });
  await expectAccessible(page);

  await page.getByRole("tab", { name: "Review bullets" }).click();
  const firstEdit = page.getByRole("radio", { name: "Edit" }).first();
  await firstEdit.click();
  const box = page.getByRole("textbox", { name: /Edit bullet for/ }).first();
  const current = await box.inputValue();
  await box.fill(`${current} Quickly.`);
  await page.getByRole("button", { name: "Update resume (no AI)" }).click();
  await expect(page.getByText(/Resume updated · \d page/)).toBeVisible({ timeout: 60_000 });

  // Recent runs: the Apply page's table, with a row menu.
  await expect(page.getByRole("heading", { name: "Recent runs" })).toBeVisible();
  await expect(page.getByRole("columnheader", { name: /Skill match/ })).toBeVisible();
  const actions = page.getByRole("button", { name: /^Actions for / }).first();
  // The menu closes on scroll: bring the row into view before opening it.
  await actions.scrollIntoViewIfNeeded();
  await page.evaluate(() => new Promise((done) => requestAnimationFrame(() => done(null))));
  await actions.click();
  await expect(page.getByRole("menuitem", { name: "Download PDF" })).toBeVisible();
  await expect(page.getByRole("menuitem", { name: "Showing above" })).toBeDisabled();
  await page.keyboard.press("Escape");
  await expectAccessible(page);
});

test("profile: one save bar validates, then saves", async ({ page }) => {
  // Groups start collapsed once onboarding is done; ?setup=1 opens them all.
  await page.goto("/profile/application?setup=1");
  await page.getByLabel("Visa status").selectOption("f1_opt");
  await expect(
    page.getByLabel("Need sponsorship in the future", { exact: true }).locator("option").first(),
  ).toHaveText("Auto from visa: Yes");
  await page.getByLabel("School email").fill("student@gmail.com");
  await page.getByRole("button", { name: "Save changes" }).click();
  await expect(page.getByRole("alert").filter({ hasText: "need" })).toBeVisible();
  await expect(page.getByLabel("School email")).toBeFocused();
  await page.getByLabel("School email").fill("student@school.edu");
  await page.getByRole("button", { name: "Save changes" }).click();
  await expect(page.getByText("All changes saved")).toBeVisible();
  await expect(page.getByLabel("Which office would you prefer?")).toHaveValue("New York");
  await expectAccessible(page);
});

test("apply page: tabs group applications by what they need", async ({ page }) => {
  await page.goto("/applications");
  await expect(page.getByRole("tab", { name: /Needs you/ })).toHaveAttribute(
    "aria-selected",
    "true",
  );
  await expect(page.getByText("Acme Capital").first()).toBeVisible();
  await expect(page.getByText("Beta Bank").first()).toBeVisible();
  await expectAccessible(page);
  await page.getByRole("tab", { name: /In progress/ }).click();
  await expect(page.getByText("Gamma Labs").first()).toBeVisible();
});

test("template page: gallery card and page fit card", async ({ page }) => {
  await page.goto("/template");
  await expect(page.getByRole("heading", { name: "Your templates" })).toBeVisible();
  await expect(page.getByText("E2E template").first()).toBeVisible();
  await expect(page.getByRole("img", { name: "First page of E2E template" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Page fit tuning" })).toBeVisible();
  await expectAccessible(page);
});

test("resume editor: coach tips and a section preset", async ({ page }) => {
  await page.goto("/profile/resume");
  await page.getByRole("button", { name: /^Expand Example Corp/ }).click();
  const bullet = page.getByRole("textbox", { name: /^Bullet / }).first();
  await bullet.fill("Responsible for the weekly report");
  await expect(page.getByText(/Starts with "Responsible for"/)).toBeVisible();
  await page.getByLabel("New section").selectOption({ label: "Awards · Honors and scholarships" });
  await page.getByRole("button", { name: "Add section" }).click();
  await expect(
    page.getByRole("navigation", { name: "Resume sections" }).getByText("Awards"),
  ).toBeVisible();
  await page.getByRole("button", { name: "Discard" }).click();
  await page.getByRole("button", { name: "Discard" }).last().click();
});

test("onboarding and settings pages render accessibly", async ({ page }) => {
  await page.goto("/welcome");
  await expect(page.getByRole("heading").first()).toBeVisible();
  await expectAccessible(page);
  await page.goto("/settings");
  await expect(page.getByRole("heading").first()).toBeVisible();
  await expectAccessible(page);
});

test("resume editor: import a PDF's content as a draft", async ({ page, request }) => {
  const pdf = await request.get("/e2e/resume.pdf");
  await page.goto("/profile/resume");
  await page.getByText("Import resume content").click();
  const panel = page.locator("section").filter({ hasText: "Import from a document" });
  await panel.locator('input[type="file"]').setInputFiles({
    name: "resume.pdf",
    mimeType: "application/pdf",
    buffer: await pdf.body(),
  });
  await page.getByRole("button", { name: "Review as draft" }).click();
  await expect(panel.getByText(/imported as an unsaved draft/)).toBeVisible();
  await expect(
    page.getByRole("navigation", { name: "Resume sections" }).getByText("CERTIFICATIONS"),
  ).toBeVisible();
  await expectAccessible(page);
  await page.getByRole("button", { name: "Discard" }).click();
  await page.getByRole("button", { name: "Discard" }).last().click();
});

test("template page: switch to a starter template", async ({ page }) => {
  await page.goto("/template");
  const starters = page.getByRole("region", { name: "Starter templates" });
  await expect(
    starters.getByRole("img", { name: "Sample page in the Compact template" }),
  ).toBeVisible();
  await starters.getByRole("button", { name: "Use Compact" }).click();
  await expect(starters.getByRole("button", { name: "In use" })).toBeVisible({ timeout: 60_000 });
  await expect(page.getByRole("heading", { name: "Compact", level: 2 })).toBeVisible();
  await expectAccessible(page);
});

test("template page: Use on a saved template moves the In use badge without a reload", async ({
  page,
}) => {
  await page.goto("/template");
  const saved = page.locator("section").filter({ hasText: "Your templates" }).first();
  const card = (label: string) => saved.locator("li").filter({ hasText: label });
  await expect(card("Compact").getByRole("button", { name: "In use" })).toBeVisible();
  // Ordinary activation reuses valid calibration and offers tuning separately.
  await card("E2E template").getByRole("button", { name: "Use", exact: true }).click();
  await expect(card("E2E template").getByRole("button", { name: "In use" })).toBeVisible({
    timeout: 90_000,
  });
  await expect(card("Compact").getByRole("button", { name: "Use", exact: true })).toBeVisible();
  await expect(page.getByRole("heading", { name: "E2E template", level: 2 })).toBeVisible();
});

test("header: pause and resume all automation", async ({ page }) => {
  await page.goto("/applications");
  const pause = page.getByRole("button", { name: "Pause automation" });
  await expect(pause).toHaveAttribute("aria-pressed", "false");
  await pause.click();
  const resume = page.getByRole("button", { name: /Automation paused/ });
  await expect(resume).toHaveAttribute("aria-pressed", "true");
  await expectAccessible(page);
  await resume.click();
  await expect(page.getByRole("button", { name: "Pause automation" })).toBeVisible();
});

test("sources: their own page, reached from Apply settings, not a tab", async ({ page }) => {
  await page.goto("/applications");
  await expect(page.getByRole("tab", { name: /^Sources/ })).toHaveCount(0);
  await page.getByRole("button", { name: "Apply settings" }).click();
  const drawer = page.getByRole("dialog", { name: "Apply settings" });
  await drawer.getByRole("link", { name: "Job sources →" }).click();
  await expect(page).toHaveURL(/\/applications\/sources$/);
  await expect(page.getByRole("heading", { name: "Job sources", level: 1 })).toBeVisible();
  await page.getByRole("link", { name: "← Applications" }).click();
  await expect(page).toHaveURL(/\/applications$/);
  // An old link to the tab lands on the page.
  await page.goto("/applications?tab=sources");
  await expect(page).toHaveURL(/\/applications\/sources$/);
});

test("sources: three groups are always visible, search engines included", async ({ page }) => {
  await page.goto("/applications/sources");
  for (const name of ["Job lists", "Search engines", "Company watchlists"])
    await expect(page.getByRole("heading", { name })).toBeVisible();
  await expect(page.getByRole("button", { name: "+ Add job list" })).toBeVisible();
  await expect(page.getByRole("button", { name: "+ Add search" })).toBeVisible();
  await expect(page.getByRole("button", { name: "+ Add watchlist" })).toBeVisible();
  await expect(page.getByRole("group", { name: "Adzuna" })).toBeVisible();
  await expect(page.getByRole("group", { name: "USAJobs" })).toBeVisible();
  await expectAccessible(page);
});

test("sources: build a company watchlist", async ({ page }) => {
  await page.goto("/applications/sources");
  await page.getByRole("button", { name: "+ Add watchlist" }).click();
  const dialog = page.getByRole("dialog", { name: "New company watchlist" });
  await expect(dialog.getByRole("button", { name: "Add watchlist" })).toBeDisabled();
  const link = dialog.getByLabel("Company careers page or job board link");
  await link.fill("https://boards.greenhouse.io/nope");
  await dialog.getByRole("button", { name: "Add company" }).click();
  await expect(dialog.getByRole("alert")).toContainText("No greenhouse job board");
  await link.fill("https://boards.greenhouse.io/acme");
  await dialog.getByRole("button", { name: "Add company" }).click();
  await expect(dialog.getByRole("button", { name: "Remove Acme Capital" })).toBeVisible();
  await expectAccessible(page);
  await dialog.getByRole("button", { name: "Add watchlist" }).click();
  await expect(dialog).toBeHidden();
  await expect(
    page
      .getByRole("region", { name: "Company watchlists" })
      .getByRole("button", { name: "Watchlist: Acme Capital", exact: true }),
  ).toBeVisible();
});

test("sources: a keyword search is added in the same panel as it is edited", async ({ page }) => {
  await page.goto("/applications/sources");
  const adzuna = page.getByRole("group", { name: "Adzuna" });
  // Keys are saved once per engine, never inside a search.
  const connected = await adzuna.getByText("● Connected").isVisible();
  await page.getByRole("button", { name: "+ Add search" }).click();
  const dialog = page.getByRole("dialog", { name: "New Adzuna search" });
  await expect(dialog.getByLabel("Adzuna app key")).toHaveCount(0);
  if (!connected) await expect(dialog.getByRole("alert")).toContainText("Connect Adzuna first");
  const phrases = dialog.getByRole("textbox", { name: "Search phrases" });
  await phrases.fill("financial analyst");
  await phrases.press("Enter");
  await dialog.getByRole("button", { name: "Add search" }).click();
  await expect(dialog).toBeHidden();
  const row = page.getByRole("region", { name: "Search engines" }).getByRole("listitem");
  await expect(row.getByText("Adzuna: financial analyst")).toBeVisible();
  // Opening it shows the same fields the new-search panel had.
  await row.locator('button[title="Edit"]').click();
  const panel = page.getByRole("dialog", { name: "Adzuna: financial analyst" });
  await expect(panel.getByRole("textbox", { name: "Search phrases" })).toBeVisible();
  await expect(panel.getByRole("textbox", { name: "Keep titles containing" })).toBeVisible();
  await expect(panel.getByRole("textbox", { name: "Skip titles containing" })).toBeVisible();
});

test("sources: remove a source, then undo", async ({ page }) => {
  await page.goto("/applications/sources");
  const headline = page.getByText(/^Searching \d+ sources?/);
  const before = (await headline.textContent()) ?? "";
  const first = page.getByRole("region", { name: "Job lists" }).getByRole("listitem").first();
  const name = (await first.locator('button[title="Edit"]').textContent()) ?? "";
  // The menu closes on any scroll, and a scroll event lands a frame after scrollIntoView.
  await first.scrollIntoViewIfNeeded();
  await page.evaluate(
    () => new Promise((done) => requestAnimationFrame(() => requestAnimationFrame(done))),
  );
  await first.getByRole("button", { name: /^Actions for / }).click();
  await page.getByRole("menuitem", { name: "Remove" }).click();
  // No confirm dialog: a toast with Undo instead.
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await expect(headline).not.toHaveText(before);
  await expect(page.getByText(`Removed ${name}`)).toBeVisible();
  await page.getByRole("button", { name: "Undo" }).click();
  await expect(headline).toHaveText(before);
  await expect(page.getByRole("switch", { name: `${name} on` })).toBeVisible();
});

test("apply settings: nightly run first, auto-submit limits off until auto-submit is on", async ({
  page,
}) => {
  await page.goto("/applications");
  await page.getByRole("button", { name: /^Nightly run: / }).click();
  const drawer = page.getByRole("dialog", { name: "Apply settings" });
  await expect(drawer.getByRole("heading", { level: 3 }).first()).toHaveText("Nightly run");
  await expect(drawer.getByLabel("New postings per nightly run")).toBeVisible();
  await expect(drawer.getByLabel("Automatic submits per 24 hours")).toBeDisabled();
  await expect(
    drawer.getByText("Auto-submit is off: every application waits for you."),
  ).toBeVisible();
  await expect(drawer.getByText("Most postings per search")).toHaveCount(0);
  await expectAccessible(page);
});
