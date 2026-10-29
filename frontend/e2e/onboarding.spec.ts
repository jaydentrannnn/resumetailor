import { expect, test } from "@playwright/test";
import { expectAccessible } from "./a11y";

// Run against an unseeded profile: E2E_FRESH=1 npx playwright test e2e/onboarding.spec.ts
test.skip(process.env.E2E_FRESH !== "1", "Requires the --fresh server, not the seeded app suite");

test("fresh setup: skip invalid drafts, optional answers, review edits and resume completion", async ({
  page,
  request,
}) => {
  await request.put("/api/onboarding", {
    data: { step: "personal", completed: false, skipped: false, skipped_steps: [] },
  });
  await page.goto("/welcome");
  await expect(
    page.getByRole("heading", { name: "Personal information", exact: true }),
  ).toBeVisible();
  await page.locator("#pf-email").fill("bad");
  await page.getByRole("button", { name: "Skip", exact: true }).click();
  await page.getByRole("dialog").getByRole("button", { name: "Cancel" }).click();
  await expect(page.locator("#pf-email")).toHaveValue("bad");
  await page.getByRole("button", { name: "Skip", exact: true }).click();
  await page.getByRole("dialog").getByRole("button", { name: "Skip", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Check your resume content" })).toBeFocused();
  await expect(page.getByRole("navigation", { name: "Setup", exact: true })).toContainText(
    "(skipped)",
  );
  await page.getByRole("button", { name: "Back", exact: true }).click();
  await expect(page.locator("#pf-email")).toHaveValue("bad");
  await page.locator("#pf-email").fill("");
  await page.getByLabel("Name on resume", { exact: true }).fill("Test Person");
  await page.getByRole("textbox", { name: "Email", exact: true }).fill("not-an-email");
  await page.getByRole("textbox", { name: "Phone", exact: true }).fill("abc");
  await expect(page.getByRole("button", { name: "Next", exact: true })).toBeDisabled();
  await page.getByRole("button", { name: "Skip setup for now" }).click();
  await page.getByRole("dialog").getByRole("button", { name: "Skip setup", exact: true }).click();
  await expect(page).toHaveURL(/\/$/);
  await page.goto("/welcome");
  await expect(
    page.getByRole("heading", { name: "Personal information", exact: true }),
  ).toBeVisible();
  // Prepare the optional application step using the real progress API.
  await request.put("/api/onboarding", {
    data: { step: "application", completed: false, skipped: false },
  });
  await page.reload();
  await expect(
    page.getByRole("heading", { name: "Application details", exact: true }),
  ).toBeVisible();
  await expect(page.getByRole("button", { name: "Next", exact: true })).toBeEnabled();
  await page.getByText("Demographics (optional)", { exact: true }).click();
  await page.getByLabel("Hispanic or Latino").selectOption("decline");
  await page.locator("#pf-eeo-gender").selectOption("");
  await expect(page.getByRole("button", { name: "Next", exact: true })).toBeEnabled();
  await page.getByRole("button", { name: "Next", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Review your setup" })).toBeVisible();
  const profile = await (await request.get("/api/applicant-profile")).json();
  expect(profile.profile.eeo.hispanic_latino_declined).toBe(true);
  await page.getByRole("button", { name: "Edit", exact: true }).first().click();
  await expect(page.getByRole("button", { name: "Save and return to review" })).toBeVisible();
  await page.getByRole("button", { name: "Save and return to review" }).click();
  await page.getByRole("button", { name: "Save and finish" }).click();
  await expect(
    page.getByRole("heading", { name: "Finish setting up when you're ready" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Review or edit setup" }).click();
  await expect(page.getByRole("heading", { name: "Review your setup" })).toBeVisible();
  await expectAccessible(page);
});

test("setup load failure offers retry", async ({ page, request }) => {
  await request.put("/api/onboarding", {
    data: { step: "field", completed: false, skipped: false },
  });
  await page.route("**/api/onboarding", (route) => route.fulfill({ status: 503, body: "{}" }));
  await page.goto("/welcome");
  await expect(page.getByRole("button", { name: "Retry", exact: true })).toBeVisible();
  await page.unroute("**/api/onboarding");
  await page.getByRole("button", { name: "Retry", exact: true }).click();
  await expect(page.getByRole("heading", { name: "What field are you targeting?" })).toBeVisible();
});

test("job lists retry, keep exclusions and lock navigation while saving", async ({
  page,
  request,
}) => {
  await request.put("/api/onboarding", {
    data: { step: "field", completed: false, skipped: false },
  });
  await page.route("**/api/apply/catalog", (route) => route.fulfill({ status: 503, body: "{}" }));
  await page.goto("/welcome");
  await expect(page.getByRole("button", { name: "Retry job lists" })).toBeVisible();
  await page.unroute("**/api/apply/catalog");
  await page.route("**/api/apply/catalog", (route) =>
    route.fulfill({
      json: {
        schema_version: 1,
        origin: "bundled",
        entries: [
          {
            id: "test-swe",
            name: "Keep excluded",
            description: "",
            fields: ["swe"],
            version: "1",
            template: {
              id: "test-swe",
              kind: "pipe_table",
              url: "https://example.com/jobs",
              categories: [],
              enabled: true,
            },
          },
        ],
      },
    }),
  );
  await page.getByRole("button", { name: "Retry job lists" }).click();
  await page.getByRole("radio", { name: /Software & Data/ }).click();
  await expect(page.getByRole("radio", { name: /Software & Data/ })).toBeChecked();
  const excluded = page.getByRole("checkbox", { name: "Keep excluded" });
  await excluded.uncheck();
  await page.getByRole("checkbox", { name: "Quant", exact: true }).check();
  await expect(excluded).not.toBeChecked();
  await page.route("**/api/onboarding", async (route) => {
    if (route.request().method() === "PUT")
      await new Promise((resolve) => setTimeout(resolve, 500));
    await route.continue();
  });
  await page.getByRole("button", { name: "Next", exact: true }).click();
  await expect(page.getByRole("button", { name: "Skip setup for now" })).toBeDisabled();
  await expect(page.getByRole("heading", { name: "Add your resume", exact: true })).toBeVisible();
});
