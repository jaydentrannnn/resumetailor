// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { useState } from "react";
import { afterEach, expect, it, vi } from "vitest";

afterEach(() => cleanup());

const empty = {
  entries: [],
  effective: { term_count: 0, tag_alias_count: 0, verb_count: 0, fingerprint: "" },
  diagnostics: [],
  proposals: [],
  warning: null,
};
const added = {
  ...empty,
  entries: [{ kind: "term", name: "quuxware", builtin: false, hidden: false, items: [] }],
};
const addVocabulary = vi.fn();

vi.mock("../api", () => ({
  fetchLibraries: vi.fn(async () => empty),
  addVocabulary: (...args: unknown[]) => addVocabulary(...args),
}));

import { LibraryProvider, useLibraryState } from "./libraryState";

function AddProbe() {
  const { entries, add, error } = useLibraryState();
  const [failure, setFailure] = useState("");
  return (
    <>
      <span data-testid="names">{entries.map((e) => e.name).join(",")}</span>
      <span data-testid="failure">{failure}</span>
      <span data-testid="error">{error ?? ""}</span>
      <button
        onClick={() => add("term", "quuxware").catch((err: Error) => setFailure(err.message))}
      >
        Add
      </button>
    </>
  );
}

it("applies the returned dictionary after an addition", async () => {
  addVocabulary.mockResolvedValueOnce(added);
  render(
    <LibraryProvider>
      <AddProbe />
    </LibraryProvider>,
  );
  fireEvent.click(screen.getByText("Add"));
  await waitFor(() => expect(screen.getByTestId("names").textContent).toBe("quuxware"));
  expect(addVocabulary).toHaveBeenCalledWith("term", "quuxware", "");
});

it("hands a refused addition back to the caller instead of the page banner", async () => {
  addVocabulary.mockRejectedValueOnce(new Error("'quuxware' is already in the dictionary."));
  render(
    <LibraryProvider>
      <AddProbe />
    </LibraryProvider>,
  );
  fireEvent.click(screen.getByText("Add"));
  await waitFor(() =>
    expect(screen.getByTestId("failure").textContent).toContain("already in the dictionary"),
  );
  expect(screen.getByTestId("error").textContent).toBe("");
});
