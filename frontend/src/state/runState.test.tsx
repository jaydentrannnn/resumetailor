// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

// Vitest isn't configured with `test.globals`, so Testing Library's automatic
// per-test cleanup (which relies on a global `afterEach`) never registers itself —
// without this, a second `describe` block's `render()` finds the previous block's
// still-mounted DOM and `getByText` starts throwing "multiple elements found".
afterEach(() => cleanup());

/**
 * Regression cover for starting a second run after one has finished.
 *
 * The SSE effect keys on `[jobId, busy]`. Flipping `busy` true while `jobId` still
 * held the *finished* job re-subscribed to that job — and `GET /api/jobs/{id}/events`
 * replays a terminal job's events and immediately sends `done` (web/app.py), which
 * restored the old report and cleared `busy`. The visible symptom was a progress tile
 * that refused to clear and a Tailor button that needed two clicks.
 */

const createJob = vi.fn();
const fetchJob = vi.fn();
const cancelJob = vi.fn();
const pdfDownload = vi.fn(async () => undefined);

vi.mock("../api", () => ({
  createJob: (...args: unknown[]) => createJob(...args),
  fetchJob: (...args: unknown[]) => fetchJob(...args),
  cancelJob: (...args: unknown[]) => cancelJob(...args),
  fetchConfig: vi.fn(async () => ({ pages: 1, experience: 3, projects: 2 })),
  fetchSettings: vi.fn(async () => ({ seeded: false, settings: { pages: 1 } })),
  saveSettings: vi.fn(async () => undefined),
  triggerPdfDownload: (...args: unknown[]) => pdfDownload(...args),
  fetchRunHistory: vi.fn(async () => []),
  fetchResumeOutline: vi.fn(async () => ({
    sections: [],
    available_contact_fields: [],
    default_contact_order: [],
    has_gpa: false,
    has_coursework: false,
    gpa_currently_shown: true,
    sections_enabled: {},
    section_mode: "fixed",
  })),
}));

vi.mock("./workspaceState", () => ({
  useWorkspaceState: () => ({ activeId: "default" }),
}));

/** Job ids whose stream should replay-and-finish, as a terminal job's really does. */
const finished = new Set<string>();
/** Job ids that finished specifically via cancellation rather than success. */
const cancelledIds = new Set<string>();

class FakeEventSource {
  static opened: string[] = [];
  private listeners: Record<string, ((e: unknown) => void)[]> = {};
  onmessage: ((e: unknown) => void) | null = null;
  onerror: (() => void) | null = null;
  closed = false;

  constructor(public url: string) {
    FakeEventSource.opened.push(url);
    const id = url.split("/")[3];
    // Mirror the server: subscribing to an already-terminal job yields `done` at once.
    if (finished.has(id) || cancelledIds.has(id)) queueMicrotask(() => this.fire("done"));
  }
  addEventListener(type: string, fn: (e: unknown) => void) {
    (this.listeners[type] ??= []).push(fn);
  }
  fire(type: string) {
    if (this.closed) return;
    for (const fn of this.listeners[type] ?? []) fn({ data: "{}" });
  }
  close() {
    this.closed = true;
  }
}

import { RunProvider, useRunState } from "./runState";

function Probe() {
  const { setJdText, startJob, cancelRun, busy, jobId, status } = useRunState();
  return (
    <div>
      <span data-testid="busy">{String(busy)}</span>
      <span data-testid="jobId">{jobId ?? "-"}</span>
      <span data-testid="status">{status ?? "-"}</span>
      <button onClick={() => setJdText("a posting")}>set-jd</button>
      <button onClick={() => void startJob()}>start</button>
      <button onClick={() => void cancelRun()}>cancel</button>
    </div>
  );
}

async function finishRun(id: string) {
  /** Drive job `id` to a successful completion through its open stream. */
  finished.add(id);
  const source = (globalThis as never as { __last: FakeEventSource }).__last;
  source.fire("done");
  await waitFor(() => expect(screen.getByTestId("busy").textContent).toBe("false"));
}

describe("RunProvider: starting a second run", () => {
  beforeEach(() => {
    finished.clear();
    cancelledIds.clear();
    FakeEventSource.opened = [];
    createJob.mockReset();
    fetchJob.mockReset();
    cancelJob.mockReset();
    cancelJob.mockResolvedValue({ status: "running" });
    fetchJob.mockImplementation(async (id: string) => ({
      status: cancelledIds.has(id) ? "cancelled" : finished.has(id) ? "succeeded" : "running",
      report: finished.has(id) ? { title: "Some Role" } : null,
      expansion: null,
      error: null,
      events: [],
      queue_position: null,
    }));
    vi.stubGlobal(
      "EventSource",
      class extends FakeEventSource {
        constructor(url: string) {
          super(url);
          (globalThis as never as { __last: FakeEventSource }).__last = this;
        }
      },
    );
  });

  it("enqueues and subscribes to the new run on a single click", async () => {
    createJob
      .mockResolvedValueOnce({ job_id: "job-A", queue_position: 1 })
      .mockResolvedValueOnce({ job_id: "job-B", queue_position: 1 });

    render(
      <RunProvider>
        <Probe />
      </RunProvider>,
    );

    fireEvent.click(screen.getByText("set-jd"));
    fireEvent.click(screen.getByText("start"));
    await waitFor(() => expect(screen.getByTestId("jobId").textContent).toBe("job-A"));
    await waitFor(() =>
      expect(FakeEventSource.opened).toContain("/api/jobs/job-A/events"),
    );

    await finishRun("job-A");

    // ONE click. Previously this re-subscribed to job-A, whose replayed `done`
    // cleared `busy` again — so the run only appeared to start on a second click.
    fireEvent.click(screen.getByText("start"));

    await waitFor(() => expect(screen.getByTestId("jobId").textContent).toBe("job-B"));
    expect(createJob).toHaveBeenCalledTimes(1 + 1);
    expect(screen.getByTestId("busy").textContent).toBe("true");
    await waitFor(() =>
      expect(FakeEventSource.opened).toContain("/api/jobs/job-B/events"),
    );
    // The finished job is never re-subscribed to.
    expect(
      FakeEventSource.opened.filter((u) => u === "/api/jobs/job-A/events"),
    ).toHaveLength(1);
  });
});

describe("RunProvider: cancelling a run", () => {
  beforeEach(() => {
    finished.clear();
    cancelledIds.clear();
    FakeEventSource.opened = [];
    createJob.mockReset();
    fetchJob.mockReset();
    cancelJob.mockReset();
    cancelJob.mockResolvedValue({ status: "running" });
    fetchJob.mockImplementation(async (id: string) => ({
      status: cancelledIds.has(id) ? "cancelled" : finished.has(id) ? "succeeded" : "running",
      report: null,
      expansion: null,
      error: null,
      events: [],
      queue_position: null,
    }));
    vi.stubGlobal(
      "EventSource",
      class extends FakeEventSource {
        constructor(url: string) {
          super(url);
          (globalThis as never as { __last: FakeEventSource }).__last = this;
        }
      },
    );
  });

  it("requests cancellation and reflects the eventual cancelled status", async () => {
    createJob.mockResolvedValueOnce({ job_id: "job-C", queue_position: 1 });

    render(
      <RunProvider>
        <Probe />
      </RunProvider>,
    );

    fireEvent.click(screen.getByText("set-jd"));
    fireEvent.click(screen.getByText("start"));
    await waitFor(() => expect(screen.getByTestId("jobId").textContent).toBe("job-C"));
    expect(screen.getByTestId("busy").textContent).toBe("true");

    fireEvent.click(screen.getByText("cancel"));
    await waitFor(() => expect(cancelJob).toHaveBeenCalledWith("job-C"));

    // The server has now marked the job cancelled; the open SSE stream delivers `done`.
    cancelledIds.add("job-C");
    const source = (globalThis as never as { __last: FakeEventSource }).__last;
    source.fire("done");

    await waitFor(() => expect(screen.getByTestId("busy").textContent).toBe("false"));
    expect(screen.getByTestId("status").textContent).toBe("cancelled");
  });
});

describe("loadRun", () => {
  beforeEach(() => {
    finished.clear();
    cancelledIds.clear();
    FakeEventSource.opened = [];
    createJob.mockReset();
    fetchJob.mockReset();
    cancelJob.mockReset();
    pdfDownload.mockReset();
    vi.stubGlobal("localStorage", {
      getItem: () => null,
      setItem: () => undefined,
      removeItem: () => undefined,
    });
  });

  it("does not re-trigger PDF download when opening a past succeeded run", async () => {
    fetchJob.mockResolvedValueOnce({
      job_id: "past-1",
      status: "succeeded",
      queue_position: null,
      error: null,
      report: {
        title: "Past Role",
        seniority: "intern",
        coverage_matched: 1,
        coverage_total: 1,
        missing_must_haves: [],
        unmatched_canonicals: [],
        gaps: [],
        model: "stub",
        semantic_used: false,
        bullets_selected: 1,
        bullets_total: 1,
        experience: [],
        projects: [],
        dropped: [],
        pages: 1,
        pages_are_estimated: true,
        iterations: 1,
        widows_repaired: 0,
        widows_remaining: 0,
        verbs_diversified: 0,
        verb_collisions_remaining: 0,
        warnings: [],
        out_path: "",
        pdf_backend: "soffice",
        calibration_source: "fallback",
      },
      expansion: null,
      skills: null,
      events: [],
    });

    function LoadProbe() {
      const { loadRun, report, jobId } = useRunState();
      return (
        <div>
          <span data-testid="jobId">{jobId ?? "-"}</span>
          <span data-testid="title">{report?.title ?? "-"}</span>
          <button onClick={() => void loadRun("past-1")}>load</button>
        </div>
      );
    }

    render(
      <RunProvider>
        <LoadProbe />
      </RunProvider>,
    );

    fireEvent.click(screen.getByText("load"));
    await waitFor(() => expect(screen.getByTestId("jobId").textContent).toBe("past-1"));
    expect(screen.getByTestId("title").textContent).toBe("Past Role");
    // Give the auto-download effect a tick — it must stay silent because
    // loadRun seeded autoDownloadedFor before setting report.
    await new Promise((r) => setTimeout(r, 30));
    expect(pdfDownload).not.toHaveBeenCalled();
  });
});
