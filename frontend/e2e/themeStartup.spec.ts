import { expect, test } from "@playwright/test";
import { readFile } from "node:fs/promises";

test("saved accent applies before paint", async ({ page }) => {
  await page.addInitScript(() => {
    localStorage.setItem("resume-tailor-theme", "light");
    localStorage.setItem("resume-tailor-accent", "#2563eb");
  });
  await page.goto("/");
  await expect(page.locator("html")).toHaveAttribute("data-accent", "");
  const accent = await page
    .locator("html")
    .evaluate((el) => (el as HTMLElement).style.getPropertyValue("--rt-accent-base").trim());
  expect(accent).toBe("#2563eb");
});

for (const theme of ["light", "dark"] as const) {
  test(`saved ${theme} theme overrides the OS during app loading and startup`, async ({ page }) => {
    await page.emulateMedia({ colorScheme: theme === "light" ? "dark" : "light" });
    await page.addInitScript(
      (preference) => localStorage.setItem("resume-tailor-theme", preference),
      theme,
    );
    let release!: () => void;
    const held = new Promise<void>((resolve) => {
      release = resolve;
    });
    await page.route("**/api/workspaces", async (route) => {
      await held;
      await route.continue();
    });
    await page.goto("/");
    await expect(page.getByRole("status")).toContainText("Loading");
    await expect(page.locator("html")).toHaveAttribute("data-theme", theme);
    const expected = theme === "dark" ? "rgb(245, 245, 244)" : "rgb(11, 11, 11)";
    await expect(page.getByRole("status").locator('[aria-hidden="true"]')).toHaveCSS(
      "background-color",
      expected,
    );
    release();
    await expect(page.getByRole("navigation", { name: "Main" })).toBeVisible();
    await expect(page.locator("html")).toHaveAttribute("data-theme", theme);
    await expect(page.locator('link[rel="icon"]')).toHaveAttribute(
      "href",
      new RegExp(`logo-mark-${theme === "dark" ? "white" : "black"}`),
    );
    await page.screenshot({ path: `test-results/theme-${theme}.png` });

    // Exercise the bundled desktop startup HTML with the same seed the shell provides.
    const html = await readFile("../desktop/ui/index.html", "utf8");
    const mark = await readFile("../desktop/ui/logo-mark.svg", "utf8");
    await page.route("**/startup/logo-mark.svg", (route) =>
      route.fulfill({ contentType: "image/svg+xml", body: mark }),
    );
    await page.route("**/startup/index.html", (route) =>
      route.fulfill({
        contentType: "text/html",
        body: html.replace(
          "<head>",
          `<head><script>window.__RT_DESKTOP_THEME__=${JSON.stringify(theme)}</script>`,
        ),
      }),
    );
    await page.goto("/startup/index.html");
    await expect(page.locator("html")).toHaveAttribute("data-theme", theme);
    await expect(page.locator(".wordmark i")).toHaveCSS("background-color", expected);
    await expect(page.locator("body")).toHaveCSS(
      "background-color",
      theme === "dark" ? "rgb(10, 10, 10)" : "rgb(255, 255, 255)",
    );
    await page.screenshot({ path: `test-results/startup-${theme}.png` });
  });
}
