import { expect, test } from "@playwright/test";

// Simple | Full view on a new install. Run against an unseeded profile:
//   E2E_FRESH=1 npx playwright test e2e/view.spec.ts
test.skip(process.env.E2E_FRESH !== "1", "Requires the --fresh server, not the seeded app suite");

test("a new install opens in Simple, switches to Full, and never hides what was set", async ({
  page,
  request,
}) => {
  // Decide the new install's view before marking setup complete (existing users get Full).
  const settings = async () => (await (await request.get("/api/settings")).json()).settings;
  const initial = await settings();
  expect(initial.ui_mode).toBe("simple");
  // Past stage 1 so the app is open, retaining the view chosen above.
  await request.put("/api/onboarding", {
    data: { completed: true, apply_done: true, guide_dismissed: true },
  });

  // Simple: the drawer leaves out auto-submit while it is off.
  await page.goto("/applications?settings=1");
  const drawer = page.getByRole("dialog", { name: "Apply settings" });
  await expect(drawer.getByRole("heading", { name: "Cover letters" })).toBeVisible();
  await expect(drawer.getByRole("heading", { name: "Auto-submit" })).toHaveCount(0);
  await expect(drawer.getByRole("heading", { name: "Nightly run" })).toHaveCount(0);
  await page.keyboard.press("Escape");

  // A link can reveal the nightly run (the guide's optional step uses this).
  await page.goto("/applications?settings=1&reveal=nightly");
  await expect(drawer.getByRole("heading", { name: "Nightly run" })).toBeVisible();
  await page.keyboard.press("Escape");

  // The sidebar switches to Full; Full shows every section.
  await page.getByRole("button", { name: /Show all features/ }).click();
  await expect.poll(async () => (await settings()).ui_mode).toBe("full");
  await page.goto("/applications?settings=1");
  await expect(drawer.getByRole("heading", { name: "Auto-submit" })).toBeVisible();

  // Turn auto-submit on in Full, switch back to Simple: the section stays.
  const current = await settings();
  await request.put("/api/settings", {
    data: {
      settings: {
        ...current,
        ui_mode: "simple",
        apply: { ...current.apply, auto_submit_enabled: true },
      },
    },
  });
  await page.goto("/applications?settings=1");
  await expect(drawer.getByRole("heading", { name: "Auto-submit" })).toBeVisible();
  await expect(page.getByRole("button", { name: /Show all features/ })).toBeVisible();

  // Leave the profile as other fresh specs expect it.
  await request.put("/api/settings", {
    data: { settings: initial },
  });
});
