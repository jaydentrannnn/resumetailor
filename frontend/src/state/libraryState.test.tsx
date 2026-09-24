// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";

afterEach(() => cleanup());

const emptyOverrides = {
  tag_aliases: {},
  tag_aliases_removed: [],
  verb_families: {},
  verb_families_removed: [],
};
const state = {
  packs: [],
  enabled_packs: [],
  overrides: emptyOverrides,
  effective: { tag_alias_count: 0, verb_count: 0, fingerprint: "" },
  diagnostics: [],
  proposals: [],
  warning: null,
};
const setLibrarySelection = vi.fn(async (_ids: string[], overrides: typeof emptyOverrides) => ({
  ...state,
  overrides,
}));

vi.mock("../api", () => ({
  fetchLibraries: vi.fn(async () => state),
  setLibrarySelection: (...args: [string[], typeof emptyOverrides]) => setLibrarySelection(...args),
}));

import { LibraryProvider, useLibraryState } from "./libraryState";

function AdditionsProbe() {
  const { editOverrides, overridesSaveState } = useLibraryState();
  return (
    <>
      <span data-testid="state">{overridesSaveState}</span>
      <button onClick={() => editOverrides({ tag_aliases: { pg: "postgresql" } })}>Edit</button>
    </>
  );
}

it("keeps the additions debounce alive when its page unmounts", async () => {
  setLibrarySelection.mockClear();
  const view = render(
    <LibraryProvider>
      <AdditionsProbe />
    </LibraryProvider>,
  );
  await waitFor(() => expect(screen.getByTestId("state").textContent).toBe("saved"));
  fireEvent.click(screen.getByText("Edit"));
  expect(screen.getByTestId("state").textContent).toBe("unsaved");
  view.rerender(
    <LibraryProvider>
      <div>Another page</div>
    </LibraryProvider>,
  );
  await waitFor(
    () =>
      expect(setLibrarySelection).toHaveBeenCalledWith(
        [],
        expect.objectContaining({ tag_aliases: { pg: "postgresql" } }),
      ),
    { timeout: 2000 },
  );
});
