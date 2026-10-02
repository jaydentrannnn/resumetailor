// @vitest-environment jsdom
import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { ApplicationRow } from "../../api";
import { useApplicationTable } from "./useApplicationTable";
import { listApplications } from "../../api";

vi.mock("../../api", () => ({
  listApplications: vi.fn(() => Promise.resolve({ applications: [], counts: {}, total: 0 })),
}));

const page = (ids: string[], total = ids.length) => ({
  applications: ids.map((id) => ({ source_job_id: id, status: "ready" }) as ApplicationRow),
  counts: {},
  total,
});

beforeEach(() => vi.mocked(listApplications).mockClear());

describe("useApplicationTable", () => {
  it("defaults the review scope to latest status first", async () => {
    renderHook(() =>
      useApplicationTable("review", "workspace", new URLSearchParams(), vi.fn(), true),
    );
    await waitFor(() => expect(listApplications).toHaveBeenCalled());
    expect(listApplications).toHaveBeenCalledWith(
      expect.objectContaining({ sort: "status_at", direction: "desc" }),
    );
  });

  it("keeps the selection when paging or resizing and drops it when the filter changes", async () => {
    vi.mocked(listApplications).mockResolvedValue(page(["a", "b"], 60));
    const setParams = vi.fn();
    const { result } = renderHook(() =>
      useApplicationTable("queue", "selection-ws", new URLSearchParams(), setParams, true),
    );
    await waitFor(() => expect(result.current.data?.total).toBe(60));
    act(() => result.current.setSelected(new Set(["a", "b"])));
    expect(result.current.selectedRows.map((r) => r.source_job_id)).toEqual(["a", "b"]);
    act(() => result.current.change({ page: "2" }));
    act(() => result.current.change({ size: "50", page: "1" }));
    expect([...result.current.selected]).toEqual(["a", "b"]);
    act(() => result.current.change({ status: "ready" }));
    expect(result.current.selected.size).toBe(0);
  });

  it("clears the selection when the search changes", async () => {
    vi.mocked(listApplications).mockResolvedValue(page(["a"]));
    const { result, rerender } = renderHook(
      ({ q }) =>
        useApplicationTable("review", "search-ws", new URLSearchParams(), vi.fn(), true, q),
      { initialProps: { q: "" } },
    );
    await waitFor(() => expect(result.current.data).not.toBeNull());
    act(() => result.current.setSelected(new Set(["a"])));
    rerender({ q: "acme" });
    await waitFor(() => expect(result.current.selected.size).toBe(0));
    expect(listApplications).toHaveBeenLastCalledWith(expect.objectContaining({ q: "acme" }));
  });

  it("drops a selected row that left the page it was on, but not rows on other pages", async () => {
    vi.mocked(listApplications).mockResolvedValue(page(["a", "b"]));
    const { result } = renderHook(() =>
      useApplicationTable("queue", "gone-ws", new URLSearchParams(), vi.fn(), true),
    );
    await waitFor(() => expect(result.current.data).not.toBeNull());
    act(() => result.current.setSelected(new Set(["a", "b"])));
    vi.mocked(listApplications).mockResolvedValue(page(["b"]));
    act(() => result.current.refresh());
    await waitFor(() => expect(result.current.selected.has("a")).toBe(false));
    expect(result.current.selected.has("b")).toBe(true);
  });
});
