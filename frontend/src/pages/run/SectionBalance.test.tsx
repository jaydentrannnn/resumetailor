// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { JobSettings } from "../../api";
import { DEFAULT_SETTINGS } from "../../state/runDefaults";
import { SectionBalance } from "./SectionBalance";

const outline = vi.hoisted(() => ({
  current: {
    sections: [
      {
        id: "work",
        title: "Work",
        kind: "experience",
        entries: [{ id: "a", label: "A", bullets: 3 }],
      },
      {
        id: "proj",
        title: "Projects",
        kind: "project",
        entries: [{ id: "p", label: "P", bullets: 2 }],
      },
    ],
    sections_enabled: { projects: true },
  },
}));
vi.mock("../../api", () => ({ fetchResumeOutline: vi.fn(async () => outline.current) }));

afterEach(cleanup);

function setup(settings: Partial<JobSettings> = {}) {
  const onChange = vi.fn();
  render(<SectionBalance settings={{ ...DEFAULT_SETTINGS, ...settings }} onChange={onChange} />);
  return onChange;
}

describe("SectionBalance", () => {
  it("turning it on writes an even split and clears the legacy share", async () => {
    const onChange = setup();
    const toggle = screen.getByRole("switch") as HTMLInputElement;
    await waitFor(() => expect(toggle.disabled).toBe(false));
    fireEvent.click(toggle);
    expect(onChange).toHaveBeenCalledWith(
      expect.objectContaining({
        section_weights: { work: 1, proj: 1 },
        experience_bullet_share: null,
      }),
    );
  });

  it("shows a saved legacy share as its split", async () => {
    setup({ experience_bullet_share: 0.65 });
    expect(await screen.findByText("about 65%")).toBeTruthy();
    expect(screen.getByText("about 35%")).toBeTruthy();
  });

  it("is disabled with one section", async () => {
    setup({ include: { ...DEFAULT_SETTINGS.include, exclude_sections: ["proj"] } });
    expect(
      await screen.findByText("Needs two or more included sections with bullets."),
    ).toBeTruthy();
    expect((screen.getByRole("switch") as HTMLInputElement).disabled).toBe(true);
  });
});
