// @vitest-environment jsdom
import { act, cleanup, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fetchSetupStatus, getApplyProgress, getOnboarding, type RunHistoryEntry } from "../api";
import { emitAppEvent } from "../lib/appEvents";
import { guideProgress } from "../lib/guide";
import { GuideProvider, useGuide } from "./guideState";

const runState = vi.hoisted(() => ({ history: [] as RunHistoryEntry[] }));
vi.mock("./runState", () => ({ useRunState: () => runState }));
vi.mock("../api", () => ({
  fetchSetupStatus: vi.fn(),
  getApplyProgress: vi.fn(),
  getOnboarding: vi.fn(),
  putOnboarding: vi.fn(),
}));

const onboarding = {
  step: "done" as const,
  field: "cs" as const,
  completed: true,
  skipped: false,
  skipped_steps: [],
  resume_from_scratch: false,
  apply_done: true,
  guide_dismissed: false,
  updated_at: "",
};
const emptyProgress = {
  found: 0,
  screened_in: 0,
  tailored: 0,
  autofilled: 0,
  sent: [],
  sent_total: 0,
  needs_you: 0,
  ready: 0,
  unscreened: 0,
  postings: [],
};
const run = (status: RunHistoryEntry["status"]): RunHistoryEntry => ({
  job_id: "guide-run",
  status,
  created_at: "2026-01-01T00:00:00Z",
  finished_at: null,
  title: "Test posting",
  error: null,
  pages: null,
  coverage_matched: null,
  coverage_total: null,
  has_pdf: status === "succeeded",
  has_docx: status === "succeeded",
});
const wrapper = ({ children }: { children: ReactNode }) => (
  <MemoryRouter initialEntries={["/applications"]}>
    <GuideProvider>{children}</GuideProvider>
  </MemoryRouter>
);

afterEach(cleanup);
beforeEach(() => {
  vi.resetAllMocks();
  runState.history = [];
  vi.mocked(getOnboarding).mockResolvedValue(onboarding);
  vi.mocked(fetchSetupStatus).mockResolvedValue({ items: [], ready: true, remaining: 0 });
  vi.mocked(getApplyProgress).mockResolvedValue(emptyProgress);
});

describe("GuideProvider", () => {
  it.each(["queued", "running", "failed", "cancelled"] as const)(
    "keeps the first resume step open for a %s run",
    async (status) => {
      runState.history = [run(status)];
      const { result } = renderHook(useGuide, { wrapper });
      await waitFor(() => expect(result.current.steps).not.toBeNull());
      expect(guideProgress(result.current.steps!).next?.id).toBe("tailor");
      expect(result.current.steps!.find((step) => step.id === "tailor")?.done).toBe(false);
    },
  );

  it("ticks the resume step when an existing run succeeds without adding a history entry", async () => {
    runState.history = [run("running")];
    const { result, rerender } = renderHook(useGuide, { wrapper });
    await waitFor(() => expect(result.current.steps).not.toBeNull());
    expect(guideProgress(result.current.steps!).next?.id).toBe("tailor");

    runState.history = [run("succeeded")];
    rerender();
    await waitFor(() =>
      expect(result.current.steps!.find((step) => step.id === "tailor")?.done).toBe(true),
    );
    expect(guideProgress(result.current.steps!).next?.id).toBe("find");
  });

  it("advances through find, fill and send on application updates without navigation", async () => {
    runState.history = [run("succeeded")];
    const { result } = renderHook(useGuide, { wrapper });
    await waitFor(() => expect(result.current.steps).not.toBeNull());
    expect(guideProgress(result.current.steps!).next?.id).toBe("find");

    for (const [progress, next] of [
      [{ found: 1, autofilled: 0, sent_total: 0 }, "fill"],
      [{ found: 1, autofilled: 1, sent_total: 0 }, "send"],
      [{ found: 1, autofilled: 1, sent_total: 1 }, undefined],
    ] as const) {
      vi.mocked(getApplyProgress).mockResolvedValue({ ...emptyProgress, ...progress });
      act(() => emitAppEvent("rt:applications-changed"));
      await waitFor(() => expect(guideProgress(result.current.steps!).next?.id).toBe(next));
    }
    expect(result.current.active).toBe(false);
  });

  it("does not fetch on application updates while the guide is hidden", async () => {
    vi.mocked(getOnboarding).mockResolvedValue({ ...onboarding, guide_dismissed: true });
    const { result } = renderHook(useGuide, { wrapper });
    await waitFor(() => expect(result.current.dismissed).toBe(true));
    act(() => emitAppEvent("rt:applications-changed"));
    expect(getOnboarding).toHaveBeenCalledTimes(1);
    expect(getApplyProgress).not.toHaveBeenCalled();
  });

  it("keeps an application update that arrives while the initial guide read is pending", async () => {
    runState.history = [run("succeeded")];
    let finish!: (value: typeof emptyProgress) => void;
    vi.mocked(getApplyProgress)
      .mockImplementationOnce(() => new Promise((resolve) => (finish = resolve)))
      .mockResolvedValueOnce({ ...emptyProgress, found: 1 });
    const { result } = renderHook(useGuide, { wrapper });
    await waitFor(() => expect(getApplyProgress).toHaveBeenCalledTimes(1));

    act(() => emitAppEvent("rt:applications-changed"));
    await waitFor(() => expect(guideProgress(result.current.steps ?? []).next?.id).toBe("fill"));
    await act(async () => finish(emptyProgress));
    expect(guideProgress(result.current.steps!).next?.id).toBe("fill");
  });
});
