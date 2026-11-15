// @vitest-environment jsdom
import { act, cleanup, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { archiveApplications, getApplication } from "../../../api";
import { onAppEvent } from "../../../lib/appEvents";
import { useApplicationDetail } from "./useApplicationDetail";

vi.mock("../../../api", () => ({
  acknowledgeApplicationResume: vi.fn(),
  archiveApplications: vi.fn(),
  correctApplicationField: vi.fn(),
  fetchJob: vi.fn(async () => ({ status: "succeeded" })),
  focusApplicationReviewTab: vi.fn(),
  getApplication: vi.fn(async (id: string) => ({
    application: { source_job_id: id, company: `Company ${id}`, status: "ready", job_id: null },
    packet: null,
    jd_text: null,
  })),
  getApplicationsRevision: vi.fn(async () => ({ workspace_id: "w", revision: 1 })),
  getApplyOperation: vi.fn(),
  refreshApplicationReview: vi.fn(),
}));
vi.mock("../../../lib/adaptivePoll", () => ({ startAdaptivePoll: () => ({ stop: () => {} }) }));

const wrapper = ({ children }: { children: ReactNode }) => <MemoryRouter>{children}</MemoryRouter>;
afterEach(cleanup);

describe("useApplicationDetail", () => {
  it("notifies the guide when an application is marked submitted in place", async () => {
    const { result } = renderHook(() => useApplicationDetail("A", "w"), { wrapper });
    await waitFor(() => expect(result.current.app?.source_job_id).toBe("A"));
    const changed = vi.fn();
    const off = onAppEvent("rt:applications-changed", changed);
    try {
      act(() => result.current.setApplication({ ...result.current.app!, status: "submitted" }));
      await waitFor(() => expect(changed).toHaveBeenCalledTimes(1));
    } finally {
      off();
    }
  });

  it("never puts an action's result for one application on another's page", async () => {
    let finish: (value: { updated: string[]; errors: Record<string, string> }) => void = () => {};
    vi.mocked(archiveApplications).mockImplementation(
      () => new Promise((resolve) => (finish = resolve)),
    );
    const { result, rerender } = renderHook(({ id }) => useApplicationDetail(id, "w"), {
      wrapper,
      initialProps: { id: "A" },
    });
    await waitFor(() => expect(result.current.app?.source_job_id).toBe("A"));

    let archiving: Promise<void> | undefined;
    act(() => {
      archiving = result.current.move();
    });
    expect(result.current.busy).toBe(true);
    rerender({ id: "B" });
    await waitFor(() => expect(result.current.app?.source_job_id).toBe("B"));
    // B's own controls are on while A's request is still out, and after it lands.
    expect(result.current.busy).toBe(false);

    vi.mocked(getApplication).mockClear();
    await act(async () => {
      finish({ updated: ["A"], errors: { A: "Busy" } });
      await archiving;
    });
    expect(result.current.app?.source_job_id).toBe("B");
    expect(result.current.error).toBeNull();
    expect(result.current.busy).toBe(false);
    expect(getApplication).not.toHaveBeenCalledWith("A");
  });
});
