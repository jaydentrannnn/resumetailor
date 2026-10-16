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

const tailored: RunHistoryEntry = {
  ...failed,
  job_id: "run-2",
  status: "succeeded",
  title: "Analyst",
  error: null,
  pages: 1,
  coverage_matched: 4,
  coverage_total: 5,
  page_coverage_matched: 3,
};
const older: RunHistoryEntry = { ...tailored, job_id: "run-3", title: "Older" };
delete older.page_coverage_matched;

vi.mock("../state/runState", () => ({
  useRunState: () => ({
    history: [failed, tailored, older],
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

  it("shows the on-page count beside the resume match, and only when the run has one", () => {
    render(<RunHistoryPanel />);
    // Each row may render in more than one layout; count per run, not in total.
    const withPage = screen.getAllByRole("progressbar", { name: "Skill match for Analyst" });
    expect(screen.getAllByRole("progressbar", { name: "Skill match for Older" })).toHaveLength(
      withPage.length,
    );
    expect(screen.getAllByText(/on page$/)).toHaveLength(withPage.length);
    expect(screen.getAllByText("3/5 on page")).toHaveLength(withPage.length);
  });
});
