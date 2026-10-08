import { expect, test } from "@playwright/test";
import { expectAccessible } from "./a11y";

test("resume content: collapse, edit, move, undo and save through the real API", async ({
  page,
  request,
}) => {
  const original = await (await request.get("/api/master-resume")).json();
  try {
    await page.goto("/profile/resume");
    const source = page.locator("#resume-section-experience");
    const heading = source.getByRole("button", { name: /^Expand Example Corp/ });
    await expect(heading).toHaveAttribute("aria-expanded", "false");
    await expect(source.getByRole("textbox", { name: "Company", exact: true })).toHaveCount(0);
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
    await source
      .getByRole("combobox", { name: /^Move Example Corp revised/ })
      .selectOption("research");
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
    await page.getByRole("button", { name: "Save changes" }).click();
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
