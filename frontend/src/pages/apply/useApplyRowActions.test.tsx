// @vitest-environment jsdom
import { act, renderHook } from "@testing-library/react";
import type { ReactNode } from "react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import { startApplyOperation, type ApplySettings } from "../../api";
import { ConfirmProvider } from "../../state/confirmState";
import { useApplyRowActions } from "./useApplyRowActions";

vi.mock("../../api", () => ({ startApplyOperation: vi.fn(async () => ({ operation_id: "op" })) }));

function mount(flushSettings: () => Promise<boolean>) {
  const wrapper = ({ children }: { children: ReactNode }) => (
    <MemoryRouter>
      <ConfirmProvider>{children}</ConfirmProvider>
    </MemoryRouter>
  );
  const showError = vi.fn();
  const { result } = renderHook(
    () =>
      useApplyRowActions({
        apply: { auto_submit_enabled: false } as ApplySettings,
        flushSettings,
        tables: [],
        openTabs: { reachable: true, target_ids: [] },
        active: false,
        exclusiveBusy: false,
        held: new Set(),
        waiting: new Set(),
        browserUsable: true,
        workspaceId: "w",
        refresh: vi.fn(),
        setOperation: vi.fn(),
        wake: vi.fn(),
        showError,
      }),
    { wrapper },
  );
  return { actions: result.current.actions, showError };
}

describe("useApplyRowActions start", () => {
  it("saves pending settings before an operation captures them", async () => {
    const order: string[] = [];
    const flush = vi.fn(async () => (order.push("flush"), true));
    vi.mocked(startApplyOperation).mockImplementation(async () => {
      order.push("start");
      return { operation_id: "op" } as never;
    });
    const { actions } = mount(flush);
    await act(() => actions.start("find"));
    expect(order).toEqual(["flush", "start"]);
  });

  it("starts nothing when the settings could not be saved", async () => {
    vi.mocked(startApplyOperation).mockClear();
    const { actions } = mount(async () => false);
    await act(() => actions.start("prepare", ["a"]));
    expect(startApplyOperation).not.toHaveBeenCalled();
  });
});
