// @vitest-environment jsdom
import { act, renderHook } from "@testing-library/react";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";
import {
  archiveApplications,
  retryApplication,
  setApplicationStatus,
  startApplyOperation,
  undoSubmitted,
  type ApplicationRow,
} from "../../../api";
import { ConfirmProvider } from "../../../state/confirmState";
import { useDetailCommands } from "./useDetailCommands";

vi.mock("../../../api", () => ({
  archiveApplications: vi.fn(async () => ({ updated: [], errors: {} })),
  getApplication: vi.fn(async () => ({ application: {} })),
  retryApplication: vi.fn(async () => ({})),
  setApplicationStatus: vi.fn(async () => ({})),
  startApplyOperation: vi.fn(async () => ({ operation_id: "op" })),
  undoSubmitted: vi.fn(async () => ({})),
}));
vi.mock("../../../state/runState", () => ({
  useRunState: () => ({
    settings: { apply: { auto_submit_enabled: false, model_provider: "claude" } },
    flushSettings: async () => true,
  }),
}));
const toast = { success: vi.fn(), error: vi.fn(), info: vi.fn(), dismiss: vi.fn() };
vi.mock("../../../lib/toast", () => ({ useToast: () => toast }));

const app = (status: string, patch: Partial<ApplicationRow> = {}): ApplicationRow =>
  ({
    source_job_id: "a1",
    company: "Acme",
    role: "Engineer",
    status,
    archived_at: null,
    job_id: "run-1",
    preparation_eligible: true,
    ...patch,
  }) as ApplicationRow;

function mount(row: ApplicationRow) {
  const reload = vi.fn(async () => {});
  const openReview = vi.fn();
  const wrapper = ({ children }: { children: ReactNode }) => (
    <ConfirmProvider>{children}</ConfirmProvider>
  );
  const { result } = renderHook(() => useDetailCommands(row, null, reload, openReview), {
    wrapper,
  });
  return { result, reload, openReview };
}

describe("useDetailCommands (audit #19)", () => {
  it("fills a ready application from its page", async () => {
    const { result, reload } = mount(app("ready"));
    expect(result.current.label).toBe("Fill");
    await act(async () => result.current.runNext());
    await vi.waitFor(() => expect(startApplyOperation).toHaveBeenCalled());
    expect(vi.mocked(startApplyOperation).mock.calls[0][0]).toMatchObject({
      action: "fill",
      application_ids: ["a1"],
      fill_mode: "initial",
    });
    await vi.waitFor(() => expect(reload).toHaveBeenCalled());
  });

  it("retries a failed tailoring", async () => {
    const { result } = mount(app("tailor_failed", { retry_kind: "tailor" }));
    expect(result.current.label).toBe("Retry");
    await act(async () => result.current.runNext());
    await vi.waitFor(() => expect(retryApplication).toHaveBeenCalledWith("a1"));
  });

  it("marks it submitted with an Undo that moves it back", async () => {
    const { result } = mount(app("awaiting_review"));
    expect(result.current.canMark).toBe(true);
    await act(async () => result.current.mark("submitted"));
    await vi.waitFor(() => expect(setApplicationStatus).toHaveBeenCalledWith("a1", "submitted"));
    await vi.waitFor(() => expect(toast.success).toHaveBeenCalled());
    const undo = toast.success.mock.calls[0][2] as { onClick: () => void };
    await act(async () => undo.onClick());
    // The mark moved it to Done: Undo restores it, which undoes the mark.
    await vi.waitFor(() => expect(archiveApplications).toHaveBeenCalledWith(["a1"], false));
    expect(undoSubmitted).not.toHaveBeenCalled();
  });

  it("keeps an action still running for one application off the next one's buttons", async () => {
    let done: () => void = () => {};
    vi.mocked(retryApplication).mockImplementationOnce(
      () => new Promise((resolve) => (done = () => resolve({} as never))),
    );
    const wrapper = ({ children }: { children: ReactNode }) => (
      <ConfirmProvider>{children}</ConfirmProvider>
    );
    const { result, rerender } = renderHook(
      ({ row }) => useDetailCommands(row, null, vi.fn(async () => {}), vi.fn()),
      { wrapper, initialProps: { row: app("tailor_failed", { retry_kind: "tailor" }) } },
    );
    act(() => result.current.runNext());
    expect(result.current.working).toBe(true);
    rerender({ row: app("ready", { source_job_id: "b2" }) });
    expect(result.current.working).toBe(false);
    await act(async () => done());
    expect(result.current.working).toBe(false);
  });

  it("offers no Mark or step on a finished application", () => {
    const { result } = mount(app("submitted", { archived_at: "2026-10-01T00:00:00Z" }));
    expect(result.current.canMark).toBe(false);
    expect(result.current.label).toBeNull();
  });
});
