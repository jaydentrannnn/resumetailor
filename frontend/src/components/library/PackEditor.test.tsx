// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { PackEditor } from "./PackEditor";

afterEach(() => cleanup());

const fetchLibraryPack = vi.fn();
vi.mock("../../api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../../api")>()),
  fetchLibraryPack: (...args: unknown[]) => fetchLibraryPack(...args),
}));

const savePack = vi.fn();
vi.mock("../../state/libraryState", () => ({
  useLibraryState: () => ({ savePack }),
}));

describe("PackEditor — round-trip casing", () => {
  it("displays a verb in its normalized casing when the pack loads a mixed-case verb", async () => {
    fetchLibraryPack.mockResolvedValueOnce({
      id: "nursing",
      label: "Nursing",
      description: "",
      builtin: false,
      customized: true,
      tag_aliases: {},
      verb_families: { care: ["Administered"] },
      created_at: "",
      updated_at: "",
    });
    render(<PackEditor packId="nursing" onClose={vi.fn()} />);
    await waitFor(() => expect(screen.getByText("administered")).toBeTruthy());
  });
});

describe("PackEditor — zero-verb family", () => {
  it("blocks save with an inline error instead of silently dropping the family", async () => {
    fetchLibraryPack.mockResolvedValueOnce({
      id: "nursing",
      label: "Nursing",
      description: "",
      builtin: false,
      customized: false,
      tag_aliases: {},
      verb_families: {},
      created_at: "",
      updated_at: "",
    });
    render(<PackEditor packId="nursing" onClose={vi.fn()} />);
    await waitFor(() => expect(screen.getByText("+ Add family")).toBeTruthy());
    // Label already loaded non-empty ("Nursing") — isolate the zero-verb-family check.

    fireEvent.click(screen.getByText("+ Add family"));
    const familyInput = screen.getByPlaceholderText("Family, e.g. care");
    fireEvent.change(familyInput, { target: { value: "care" } });

    const saveButton = screen.getByText("Save pack") as HTMLButtonElement;
    expect(saveButton.disabled).toBe(true);
    fireEvent.click(saveButton);
    expect(savePack).not.toHaveBeenCalled();
  });
});

describe("PackEditor — client-side validation blocks submit", () => {
  it("disables Save and never calls savePack when the label is empty", async () => {
    render(<PackEditor packId={null} onClose={vi.fn()} />);
    const saveButton = screen.getByText("Save pack") as HTMLButtonElement;
    expect(saveButton.disabled).toBe(true);
    fireEvent.click(saveButton);
    expect(savePack).not.toHaveBeenCalled();
  });

  it("enables Save once the label is filled and no other errors exist", async () => {
    render(<PackEditor packId={null} onClose={vi.fn()} />);
    const labelInput = screen.getByPlaceholderText("e.g. Nursing");
    fireEvent.change(labelInput, { target: { value: "Nursing" } });
    const saveButton = screen.getByText("Save pack") as HTMLButtonElement;
    expect(saveButton.disabled).toBe(false);
  });
});
