import AxeBuilder from "@axe-core/playwright";
import { expect, type Page } from "@playwright/test";

async function blockingViolations(page: Page): Promise<string[]> {
  const results = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa"]).analyze();
  return results.violations
    .filter((v) => v.impact === "serious" || v.impact === "critical")
    .map(
      (v) =>
        `${v.id} (${v.impact}): ${v.help} — ${v.nodes.map((n) => n.target.join(" ")).join(", ")}`,
    );
}

/** Fail on serious or critical accessibility violations on the current page, checked in
 *  the light theme and again in the dark theme (most dark-only colours live there). */
export async function expectAccessible(page: Page) {
  const previous = await page.evaluate(() => document.documentElement.dataset.theme ?? null);
  for (const theme of ["light", "dark"] as const) {
    await page.evaluate((t) => {
      document.documentElement.dataset.theme = t;
    }, theme);
    const blocking = await blockingViolations(page);
    expect(blocking, `[${theme}] ${blocking.join("\n")}`).toEqual([]);
  }
  await page.evaluate((t) => {
    if (t === null) delete document.documentElement.dataset.theme;
    else document.documentElement.dataset.theme = t;
  }, previous);
}
