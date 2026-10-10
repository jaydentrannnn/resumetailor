// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { JobSettings } from "../api";
import { DEFAULT_SETTINGS } from "../state/runDefaults";
import { IncludePanel } from "./IncludePanel";

const outline = vi.hoisted(() => ({
  current: {
    available_contact_fields: ["email"],
    default_contact_order: ["email"],
    has_gpa: true,
    gpa_currently_shown: true,
    has_coursework: true,
    experience: [],
    projects: [],
    sections: [
      {
        id: "work",
        title: "Work",
        kind: "experience",
        entries: [
          { id: "a", label: "Acme — Engineer", bullets: 3 },
          { id: "b", label: "Beta — Intern", bullets: 1 },
        ],
      },
      {
        id: "skills",
        title: "Skills",
        kind: "skills",
        entries: [{ id: "Tools", label: "Tools", bullets: 0, detail: "Git, Docker" }],
      },
      {
        id: "edu",
        title: "Education",
        kind: "education",
        entries: [{ id: "State U|BS", label: "State U — BS", bullets: 0, detail: "2024" }],
      },
    ],
    sections_enabled: { projects: true },
    section_mode: "generic",
  },
}));
vi.mock("../api", () => ({ fetchResumeOutline: vi.fn(async () => outline.current) }));

afterEach(cleanup);

function setup(settings: Partial<JobSettings> = {}) {
  const onChange = vi.fn();
  render(<IncludePanel settings={{ ...DEFAULT_SETTINGS, ...settings }} onChange={onChange} />);
  return onChange;
}

describe("IncludePanel", () => {
  it("lists sections collapsed, with a summary", async () => {
    setup({ include: { ...DEFAULT_SETTINGS.include, exclude_entries: ["b"] } });
    const work = await screen.findByRole("button", { name: /^Work/ });
    expect(work.getAttribute("aria-expanded")).toBe("false");
    expect(screen.getByText("· 1 of 2 included")).toBeTruthy();
    expect(screen.queryByText("Acme — Engineer")).toBeNull();
  });

  it("expanding a skills row shows its groups and toggles them", async () => {
    const onChange = setup();
    fireEvent.click(await screen.findByRole("button", { name: /^Skills/ }));
    expect(screen.getByText("Git, Docker")).toBeTruthy();
    fireEvent.click(screen.getByRole("switch"));
    expect(onChange).toHaveBeenCalledWith(
      expect.objectContaining({
        include: expect.objectContaining({ exclude_skill_groups: ["Tools"] }),
      }),
    );
  });

  it("education row holds the GPA and coursework switches", async () => {
    setup();
    fireEvent.click(await screen.findByRole("button", { name: /^Education/ }));
    expect(screen.getByText("Show GPA")).toBeTruthy();
    expect(screen.getByText("State U — BS")).toBeTruthy();
  });

  it("follows the per-run section order", async () => {
    setup({ include: { ...DEFAULT_SETTINGS.include, section_order: ["edu", "work"] } });
    await screen.findByRole("button", { name: /^Work/ });
    const titles = screen
      .getAllByRole("button", { name: /^(Work|Skills|Education)/ })
      .filter((b) => b.hasAttribute("aria-expanded"))
      .map((b) => b.textContent);
    expect(titles[0]).toMatch(/Education/);
    expect(titles[1]).toMatch(/Work/);
  });
});
