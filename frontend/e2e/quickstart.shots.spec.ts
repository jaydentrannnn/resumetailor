import { fileURLToPath } from "node:url";
import { expect, test } from "@playwright/test";

// Regenerates the screenshots in docs/QUICKSTART.md from the seeded demo profile (synthetic
// data, canned model replies), so they are never hand-made and hold no one's details:
//   E2E_SHOTS=1 npx playwright test e2e/quickstart.shots.spec.ts
test.skip(process.env.E2E_SHOTS !== "1", "Only when regenerating the quick-start screenshots");
test.skip(process.env.E2E_FRESH === "1", "Needs the seeded server");

const OUT = fileURLToPath(new URL("../../docs/quickstart/", import.meta.url));

const JD = `Data Analyst Intern
We are hiring a data analyst intern. You will use Python and SQL to build dashboards,
work with stakeholders, and present findings. Experience with search and ranking helps.`;

test("quick-start screenshots", async ({ page, request }) => {
  const setup = (data: Record<string, unknown>) => request.put("/api/onboarding", { data });
  const shot = (name: string) => page.screenshot({ path: `${OUT}${name}.png` });
  await page.setViewportSize({ width: 1280, height: 800 });
  await page.emulateMedia({ colorScheme: "light" });

  // 1. The first setup stage, as a new student meets it.
  await setup({ step: "field", completed: false, skipped: false, apply_done: false });
  await page.goto("/welcome");
  await expect(page.getByRole("heading", { name: "What field are you targeting?" })).toBeVisible();
  await shot("1-setup");

  // 2. Tailor, with the guide beside the posting.
  await setup({ step: "personal", completed: true, guide_dismissed: false });
  await page.goto("/");
  await expect(page.getByRole("region", { name: "Getting started" })).toBeVisible();
  await page.getByLabel("Job description text").fill(JD);
  await shot("2-tailor");

  // 3. The tailored bullets beside the originals. Only the left pane: headless Chromium
  // leaves the PDF preview on the right blank.
  await page.getByRole("button", { name: "Tailor resume" }).click();
  await expect(page.getByRole("tab", { name: "Review bullets" })).toBeVisible({ timeout: 90_000 });
  await page.getByRole("tab", { name: "Review bullets" }).click();
  await expect(page.getByRole("radio", { name: "Edit" }).first()).toBeVisible();
  await page
    .getByRole("region", { name: "Job and results" })
    .screenshot({ path: `${OUT}3-result.png` });

  // 4. The second setup stage.
  await page.goto("/welcome");
  await expect(page.getByText("Applying · Step 1 of 4")).toBeVisible();
  await shot("4-set-up-applying");

  // 5 and 6. Apply and Tracker, with the demo postings.
  await page.goto("/applications");
  await page.getByRole("tab", { name: /In progress/ }).click();
  await expect(page.getByText("Gamma Labs").first()).toBeVisible();
  await shot("5-apply");
  // One demo application marked sent, so Tracker has something to show.
  await page.goto("/applications/e2e-review");
  await page.getByRole("button", { name: "Mark submitted" }).click();
  await expect(page.getByRole("button", { name: "Undo" })).toBeVisible();
  await page.goto("/tracker");
  await expect(page.getByText("Nothing in Done yet")).toHaveCount(0);
  await page.waitForTimeout(1_000);
  await shot("6-tracker");

  // Leave the profile as the seeded suite expects it: nothing sent, an established user.
  // The mark moved the row to Done; restoring it from Done is what undoes the mark.
  const restored = await request.post("/api/applications/archive", {
    data: { application_ids: ["e2e-review"], archived: false },
  });
  expect((await restored.json()).updated).toEqual(["e2e-review"]);
  await setup({ completed: true, apply_done: true, guide_dismissed: true });
});
