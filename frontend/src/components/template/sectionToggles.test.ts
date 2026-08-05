import { describe, expect, it } from "vitest";

/**
 * Pure helpers mirroring wizard enablement rules (no React mount required).
 */
function nextEnabled(
  enabled: Record<string, boolean>,
  key: string,
  value: boolean,
): Record<string, boolean> {
  if (key === "experience") return enabled;
  return { ...enabled, [key]: value };
}

describe("template wizard section toggles", () => {
  it("refuses to disable experience", () => {
    const enabled = {
      education: true,
      experience: true,
      projects: true,
      skills: true,
      list_section: false,
    };
    expect(nextEnabled(enabled, "experience", false).experience).toBe(true);
  });

  it("allows omitting projects", () => {
    const enabled = {
      education: true,
      experience: true,
      projects: true,
      skills: true,
      list_section: false,
    };
    expect(nextEnabled(enabled, "projects", false).projects).toBe(false);
  });

  it("allows enabling the new list_section kind", () => {
    const enabled = {
      education: true,
      experience: true,
      projects: true,
      skills: true,
      list_section: false,
    };
    expect(nextEnabled(enabled, "list_section", true).list_section).toBe(true);
  });
});
