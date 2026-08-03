// @vitest-environment jsdom
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

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

vi.mock("../api", () => ({
  createJob: (...args: unknown[]) => createJob(...args),
  fetchJob: (...args: unknown[]) => fetchJob(...args),
  fetchConfig: vi.fn(async () => ({ pages: 1, experience: 3, projects: 2 })),
  fetchSettings: vi.fn(async () => ({ seeded: false, settings: { pages: 1 } })),
  saveSettings: vi.fn(async () => undefined),
  triggerPdfDownload: vi.fn(async () => undefined),
}));

vi.mock("./workspaceState", () => ({
  useWorkspaceState: () => ({ activeId: "default" }),
}));

/** Job ids whose stream should replay-and-finish, as a terminal job's really does. */
const finished = new Set<string>();

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
    if (finished.has(id)) queueMicrotask(() => this.fire("done"));
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
  const { setJdText, startJob, busy, jobId } = useRunState();
  return (
    <div>
      <span data-testid="busy">{String(busy)}</span>
      <span data-testid="jobId">{jobId ?? "-"}</span>
      <button onClick={() => setJdText("a posting")}>set-jd</button>
      <button onClick={() => void startJob()}>start</button>
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
    FakeEventSource.opened = [];
    createJob.mockReset();
    fetchJob.mockReset();
    fetchJob.mockImplementation(async (id: string) => ({
      status: finished.has(id) ? "succeeded" : "running",
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
