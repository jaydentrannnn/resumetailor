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
});

test("profile: one save bar validates, then saves", async ({ page }) => {
  await page.goto("/profile/application");
  await page.getByLabel("Visa status").selectOption("f1_opt");
  await expect(page.getByText("Auto from visa: Yes").first()).toBeVisible();
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
  await page.getByLabel("Tune page fit when switching").uncheck();
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
  // Page-fit tuning on, as it is by default: the slow path the owner hit.
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

test("apply settings: build a company watchlist", async ({ page }) => {
  await page.goto("/applications");
  await page.getByRole("button", { name: "Apply settings" }).click();
  await page.getByRole("button", { name: "Add a company watchlist" }).click();
  const link = page.getByLabel("Job board link");
  await link.fill("https://boards.greenhouse.io/nope");
  await page.getByRole("button", { name: "Add company" }).click();
  await expect(page.getByRole("alert")).toContainText("No greenhouse job board");
  await link.fill("https://boards.greenhouse.io/acme");
  await page.getByRole("button", { name: "Add company" }).click();
  await expect(page.getByRole("button", { name: "Remove Acme Capital" })).toBeVisible();
  await expectAccessible(page);
});
