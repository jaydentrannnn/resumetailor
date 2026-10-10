// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { DEFAULT_SETTINGS } from "../../state/runDefaults";
import { RunOptionsForm } from "./RunOptionsForm";

const outline = vi.hoisted(() => ({
  current: {
    available_contact_fields: [],
    default_contact_order: [],
    has_gpa: false,
    gpa_currently_shown: false,
    has_coursework: false,
    experience: [],
    projects: [],
    sections: [
      {
        id: "proj",
        title: "Projects",
        kind: "project",
        entries: [{ id: "p", label: "P", bullets: 2 }],
      },
    ],
    sections_enabled: { projects: true } as Record<string, boolean>,
    section_mode: "generic",
  },
}));
vi.mock("../../api", () => ({ fetchResumeOutline: vi.fn(async () => outline.current) }));

afterEach(cleanup);

function setup() {
  try {
    window.localStorage.setItem("rt.runOptions.open.w", "1");
  } catch {
    /* jsdom storage unavailable */
  }
  const onChange = vi.fn();
  render(
    <RunOptionsForm
      config={null}
      settings={DEFAULT_SETTINGS}
      onChange={onChange}
      disabled={false}
      workspaceId="w"
    />,
  );
  return onChange;
}

describe("RunOptionsForm project links", () => {
  it("sits in the options column and writes no_project_links", async () => {
    const onChange = setup();
    const label = await screen.findByText("Show project links");
    fireEvent.click(label);
    expect(onChange).toHaveBeenCalledWith(expect.objectContaining({ no_project_links: true }));
  });

  it("is hidden when the template has no projects section", async () => {
    outline.current.sections_enabled = { projects: false };
    setup();
    await screen.findByText("What to include");
    expect(screen.queryByText("Show project links")).toBeNull();
    outline.current.sections_enabled = { projects: true };
  });
});
