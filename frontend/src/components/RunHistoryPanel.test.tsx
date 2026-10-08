// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { RunHistoryEntry } from "../api";
import { RunHistoryPanel } from "./RunHistoryPanel";

const failed: RunHistoryEntry = {
  job_id: "run-1",
  status: "failed",
  created_at: "2026-10-01T00:00:00Z",
  finished_at: "2026-10-01T00:05:00Z",
  title: "Engineer",
  company: "Acme",
  error: "Model call timed out\nTraceback line two",
  pages: null,
  coverage_matched: null,
  coverage_total: null,
  has_pdf: false,
  has_docx: false,
};

vi.mock("../state/runState", () => ({
  useRunState: () => ({
    history: [failed],
    jobId: null,
    loadRun: vi.fn(),
    busy: false,
    deleteHistoryRuns: vi.fn(),
    refreshHistory: vi.fn(),
  }),
}));
vi.mock("../state/confirmState", () => ({ useConfirm: () => ({ confirm: vi.fn() }) }));

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("RunHistoryPanel", () => {
  it("shows a failed run's error on one line, with the full text a click away", () => {
    vi.spyOn(HTMLElement.prototype, "scrollWidth", "get").mockReturnValue(400);
    vi.spyOn(HTMLElement.prototype, "clientWidth", "get").mockReturnValue(100);
    render(<RunHistoryPanel />);
    const [line] = screen.getAllByRole("button", { name: /^Error details: Model call timed out/ });
    expect(line.className).toContain("truncate");
    fireEvent.click(line, { clientX: 20, clientY: 20 });
    expect(screen.getByRole("dialog", { name: "Error details" }).textContent).toContain(
      "Traceback line two",
    );
  });
});
