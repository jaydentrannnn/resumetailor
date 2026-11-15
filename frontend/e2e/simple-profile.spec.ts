import { expect, test, type APIRequestContext, type Page } from "@playwright/test";

test.beforeEach(async ({ page, request }) => {
  const { settings } = await (await request.get("/api/settings")).json();
  await request.put("/api/settings", { data: { settings: { ...settings, ui_mode: "simple" } } });
  await page.route("**/api/onboarding", (route) =>
    route.fulfill({
      json: { completed: true, skipped: false, apply_done: true, guide_dismissed: true },
    }),
  );
});

async function showProfile(
  page: Page,
  request: APIRequestContext,
  patch: Record<string, unknown>,
  gaps: unknown[] = [],
  tab = "application",
) {
  const base = await (await request.get("/api/applicant-profile")).json();
  await page.route("**/api/applicant-profile", (route) =>
    route.fulfill({
      json: {
        ...base,
        profile: { ...base.profile, ...patch },
        gaps,
        defaults: {},
        fallbacks: {},
        workday_password_set: false,
      },
    }),
  );
  await page.goto(`/profile/${tab}`);
}

test("a saved optional salary stays editable while replacing its value", async ({
  page,
  request,
}) => {
  await showProfile(page, request, { salary_yearly_max: 90000 });
  const salary = page.locator("#pf-salary_yearly_max");
  await expect(salary).toHaveValue("90000");
  await salary.fill("");
  await expect(salary).toBeFocused();
  await salary.fill("100000");
  await expect(salary).toHaveValue("100000");
});

test("saved optional names and application contact stay editable when cleared", async ({
  page,
  request,
}) => {
  await showProfile(
    page,
    request,
    { middle_name: "Marie", email: "student@example.test" },
    [],
    "personal",
  );
  for (const [id, replacement] of [
    ["middle_name", "Alex"],
    ["email", "new@example.test"],
  ]) {
    const field = page.locator(`#pf-${id}`);
    await expect(field).toBeVisible();
    await field.fill("");
    await expect(field).toBeFocused();
    await field.fill(replacement);
    await expect(field).toHaveValue(replacement);
  }
});

test("a form-reported language gap opens an empty language editor", async ({ page, request }) => {
  await showProfile(page, request, { languages: [] }, [
    {
      key: "languages",
      label: "Languages",
      section: "Languages",
      path: "/profile/application",
      seen_in: 1,
    },
  ]);
  await page.getByRole("button", { name: /Languages.*met in 1 application/ }).click();
  await page.getByRole("button", { name: "+ Add language", exact: true }).click();
  const language = page.getByPlaceholder("e.g. Vietnamese");
  await language.fill("Spanish");
  await expect(language).toHaveValue("Spanish");
});

test("saved transcript and portfolio files keep their Replace and Remove controls", async ({
  page,
  request,
}) => {
  await showProfile(page, request, {
    transcript_path: "files/transcript.pdf",
    portfolio_path: "files/portfolio.pdf",
  });
  for (const kind of ["transcript", "portfolio"]) {
    const upload = page.locator(`#profile-field-${kind}_path`);
    await expect(upload.getByText(`${kind}.pdf saved`, { exact: true })).toBeVisible();
    await expect(upload.getByRole("button", { name: "Replace", exact: true })).toBeVisible();
    await expect(upload.getByRole("button", { name: "Remove", exact: true })).toBeVisible();
  }
});
