import { expect, type Page, test } from "@playwright/test";
import { expectAccessible } from "./a11y";

// The same actions on Apply's list and on an application's own page (audit #1, #2, #19),
// and a list that follows changes made elsewhere (#17). Each test puts its rows back.

async function status(page: Page, id: string): Promise<string> {
  return page.evaluate(async (row) => {
    const response = await fetch(`/api/applications/${row}`);
    return (await response.json()).application.status as string;
  }, id);
}

async function post(page: Page, path: string, body: unknown): Promise<void> {
  await page.evaluate(
    async ([url, data]) => {
      const response = await fetch(url as string, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(data),
      });
      if (!response.ok) throw new Error(`${url}: ${response.status}`);
    },
    [path, body],
  );
}

test("application page: next step, Mark submitted and Undo in its header", async ({ page }) => {
  await page.goto("/applications/e2e-review");
  await expect(page.getByRole("button", { name: "Review", exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Skip", exact: true })).toBeVisible();
  await expectAccessible(page);

  await page.getByRole("button", { name: "Mark submitted" }).click();
  await expect.poll(() => status(page, "e2e-review")).toBe("submitted");
  await expect(page.getByRole("button", { name: "Mark submitted" })).toHaveCount(0);
  await page.getByRole("button", { name: "Undo" }).click();
  await expect.poll(() => status(page, "e2e-review")).toBe("awaiting_review");
  await expect(page.getByRole("button", { name: "Mark submitted" })).toBeVisible();
});

test("apply list: bulk Mark submitted asks first, and Undo puts the rows back", async ({
  page,
}) => {
  await page.goto("/applications");
  await page.getByRole("checkbox", { name: "Select Acme Capital Summer Analyst" }).check();
  await page.getByRole("checkbox", { name: "Select Beta Bank Analyst Intern" }).check();
  await page.getByRole("button", { name: "Mark submitted (2)" }).click();
  const dialog = page.getByRole("dialog");
  await expect(dialog).toContainText("Mark 2 applications submitted?");
  await dialog.getByRole("button", { name: "Mark submitted" }).click();
  await expect.poll(() => status(page, "e2e-otp")).toBe("submitted");
  await expect.poll(() => status(page, "e2e-review")).toBe("submitted");
  // The selection clears once the rows are marked (the bar stays, its actions off).
  await expect(page.getByRole("button", { name: "Mark submitted (0)" })).toBeDisabled();

  await page.getByRole("button", { name: "Undo" }).click();
  await expect.poll(() => status(page, "e2e-otp")).toBe("awaiting_otp");
  await expect.poll(() => status(page, "e2e-review")).toBe("awaiting_review");
  await expect(page.getByText("Beta Bank").first()).toBeVisible();
});

test("apply list: a change made elsewhere shows without a reload", async ({ page }) => {
  await page.goto("/applications");
  await page.getByRole("tab", { name: /In progress/ }).click();
  await expect(page.getByText("Gamma Labs").first()).toBeVisible();

  // Another tab, the extension or Claude Desktop skips it.
  await post(page, "/api/applications/e2e-queued/status", { status: "skipped" });
  await expect(page.getByText("Gamma Labs")).toHaveCount(0, { timeout: 30_000 });

  await post(page, "/api/applications/archive", {
    application_ids: ["e2e-queued"],
    archived: false,
  });
  await expect.poll(() => status(page, "e2e-queued")).toBe("screened_in");
  await expect(page.getByText("Gamma Labs").first()).toBeVisible({ timeout: 30_000 });
});
