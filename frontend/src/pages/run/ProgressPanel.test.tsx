// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";

const state = vi.hoisted(() => ({ value: {} as Record<string, unknown> }));
vi.mock("../../state/runState", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../state/runState")>();
  return { ...actual, useRunState: () => state.value };
});

import { DEFAULT_SETTINGS } from "../../state/runDefaults";
import { ProgressPanel } from "./ProgressPanel";

afterEach(cleanup);

const base = {
  config: null,
  settings: DEFAULT_SETTINGS,
  status: "running",
  events: [
    { stage: "extract", message: "Extracting", detail: {} },
    { stage: "rewrite", message: "Rewriting 12 bullets", detail: {} },
  ],
  report: null,
  error: null,
  busy: true,
  queuePosition: null,
  cancelRun: async () => {},
  cancelling: false,
  history: [],
};

describe("ProgressPanel", () => {
  it("shows the plain step in flight and keeps the raw log under Details", () => {
    state.value = base;
    render(<ProgressPanel />);
    const current = screen.getByRole("listitem", { current: "step" });
    expect(current.textContent).toContain("Rewriting bullets");
    expect(screen.getByText("Details (2)")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Cancel" })).toBeTruthy();
  });

  it("marks the failing step and shows the error", () => {
    state.value = { ...base, status: "failed", busy: false, error: "Model unreachable" };
    render(<ProgressPanel />);
    expect(screen.getByRole("alert").textContent).toBe("Model unreachable");
    expect(screen.getByText("(failed)")).toBeTruthy();
  });
});
