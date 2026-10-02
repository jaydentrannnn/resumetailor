// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { activateTemplateLibrary, fetchTemplateSnapshot, type TemplateSnapshot } from "../api";
import { TemplateProvider, useTemplateState } from "./templateState";

vi.mock("../api", async (original) => ({
  ...(await original<typeof import("../api")>()),
  activateTemplateLibrary: vi.fn(),
  fetchTemplateSnapshot: vi.fn(),
}));
vi.mock("../lib/toast", () => ({ useToast: () => ({ error: vi.fn() }) }));
afterEach(cleanup);
beforeEach(() => vi.clearAllMocks());

function snapshot(id: string): TemplateSnapshot {
  return {
    info: { active_label: id, active_library_id: id },
    library: {
      active_id: id,
      entries: [
        { id: "A", label: "A", is_active: id === "A" },
        { id: "B", label: "B", is_active: id === "B" },
      ],
    },
    defaults: [
      { name: "A", label: "A", is_active: id === "A" },
      { name: "B", label: "B", is_active: id === "B" },
    ],
    preview_revision: id.repeat(64),
  } as unknown as TemplateSnapshot;
}
function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => {
    resolve = done;
  });
  return { promise, resolve };
}
function Controls() {
  const state = useTemplateState();
  return (
    <>
      <span data-testid="state">
        {JSON.stringify({
          active: state.info?.active_library_id,
          library: state.libraryActiveId,
          preview: state.previewRevision,
          pending: state.pendingTemplate,
          activeDefaults: state.defaults.filter((d) => d.is_active).map((d) => d.name),
        })}
      </span>
      <button onClick={() => void state.refresh()}>Refresh</button>
      <button onClick={() => void state.activateLibraryEntry("B")}>Switch</button>
    </>
  );
}
describe("template switching", () => {
  it("commits one server snapshot and rejects an older refresh response", async () => {
    vi.mocked(fetchTemplateSnapshot).mockResolvedValueOnce(snapshot("A"));
    const stale = deferred<TemplateSnapshot>();
    vi.mocked(fetchTemplateSnapshot).mockReturnValueOnce(stale.promise);
    const switchRequest = deferred<Awaited<ReturnType<typeof activateTemplateLibrary>>>();
    vi.mocked(activateTemplateLibrary).mockReturnValue(switchRequest.promise);
    render(
      <TemplateProvider>
        <Controls />
      </TemplateProvider>,
    );
    await waitFor(() => expect(screen.getByTestId("state").textContent).toContain('"active":"A"'));
    fireEvent.click(screen.getByText("Refresh"));
    fireEvent.click(screen.getByText("Switch"));
    expect(screen.getByTestId("state").textContent).toContain('"pending":"B"');
    fireEvent.click(screen.getByText("Switch"));
    expect(activateTemplateLibrary).toHaveBeenCalledTimes(1);
    expect(activateTemplateLibrary).toHaveBeenCalledWith("B", { calibrate: false });
    await act(async () =>
      switchRequest.resolve({
        ok: true,
        log: "",
        info: snapshot("B").info,
        snapshot: snapshot("B"),
      }),
    );
    await act(async () => stale.resolve(snapshot("A")));
    const state = JSON.parse(screen.getByTestId("state").textContent!);
    expect(state).toEqual({
      active: "B",
      library: "B",
      preview: "B".repeat(64),
      pending: null,
      activeDefaults: ["B"],
    });
  });

  it("reconciles the actual server state after a failed activation", async () => {
    vi.mocked(fetchTemplateSnapshot)
      .mockResolvedValueOnce(snapshot("A"))
      .mockResolvedValueOnce(snapshot("B"));
    vi.mocked(activateTemplateLibrary).mockRejectedValueOnce(new Error("late timeout"));
    render(
      <TemplateProvider>
        <Controls />
      </TemplateProvider>,
    );
    await waitFor(() => expect(screen.getByTestId("state").textContent).toContain('"active":"A"'));
    fireEvent.click(screen.getByText("Switch"));
    await waitFor(() => expect(screen.getByTestId("state").textContent).toContain('"active":"B"'));
    expect(screen.getByTestId("state").textContent).toContain('"pending":null');
  });
});
