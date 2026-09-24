// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { KeyValueListField } from "./KeyValueListField";

// Vitest isn't configured with `test.globals`, so Testing Library's automatic
// per-test cleanup never registers itself — see runState.test.tsx for the same note.
afterEach(() => cleanup());

function getRowInputs(key: string): { keyInput: HTMLInputElement; valueInput: HTMLInputElement } {
  const keyInput = screen.getByDisplayValue(key) as HTMLInputElement;
  const row = keyInput.closest("div")!;
  const valueInput = row.querySelectorAll("input")[1] as HTMLInputElement;
  return { keyInput, valueInput };
}

describe("KeyValueListField — emit cadence", () => {
  it("does not call onChange while typing, only on blur", () => {
    const onChange = vi.fn();
    render(<KeyValueListField label="Aliases" items={{ py: "python" }} onChange={onChange} />);
    const { valueInput } = getRowInputs("py");
    fireEvent.change(valueInput, { target: { value: "pyt" } });
    fireEvent.change(valueInput, { target: { value: "pyth" } });
    fireEvent.change(valueInput, { target: { value: "python3" } });
    expect(onChange).not.toHaveBeenCalled();
    fireEvent.blur(valueInput);
    expect(onChange).toHaveBeenCalledWith({ py: "python3" });
  });

  it("does not call onChange on a blur with no actual change", () => {
    const onChange = vi.fn();
    render(<KeyValueListField label="Aliases" items={{ py: "python" }} onChange={onChange} />);
    const { valueInput } = getRowInputs("py");
    fireEvent.blur(valueInput);
    expect(onChange).not.toHaveBeenCalled();
  });
});

describe("KeyValueListField — renaming a key", () => {
  it("preserves row position instead of moving the row to the end", () => {
    const onChange = vi.fn();
    render(
      <KeyValueListField label="Aliases" items={{ a: "1", b: "2", c: "3" }} onChange={onChange} />,
    );
    const { keyInput } = getRowInputs("a");
    fireEvent.change(keyInput, { target: { value: "z" } });
    fireEvent.blur(keyInput);
    expect(onChange).toHaveBeenCalledWith({ z: "1", b: "2", c: "3" });
    expect(Object.keys(onChange.mock.calls[0][0])).toEqual(["z", "b", "c"]);
  });

  it("does not remount the row — the sibling value input keeps its in-progress text", () => {
    render(<KeyValueListField label="Aliases" items={{ a: "1" }} onChange={vi.fn()} />);
    const { keyInput, valueInput } = getRowInputs("a");
    fireEvent.change(valueInput, { target: { value: "unsaved-draft" } });
    fireEvent.change(keyInput, { target: { value: "renamed" } });
    expect((valueInput as HTMLInputElement).value).toBe("unsaved-draft");
  });
});

describe("KeyValueListField — re-sync from an external items prop", () => {
  it("rebuilds rows when items genuinely differs from what was last emitted", () => {
    const { rerender } = render(
      <KeyValueListField label="Aliases" items={{ a: "1" }} onChange={vi.fn()} />,
    );
    rerender(<KeyValueListField label="Aliases" items={{ a: "1", b: "2" }} onChange={vi.fn()} />);
    expect(screen.getByDisplayValue("b")).toBeTruthy();
  });

  it("does not rebuild (and so does not clobber an in-progress edit) when items is deep-equal to what was last emitted, even as a new object", () => {
    const onChange = vi.fn();
    const { rerender } = render(
      <KeyValueListField label="Aliases" items={{ a: "1" }} onChange={onChange} />,
    );
    const { valueInput } = getRowInputs("a");
    fireEvent.change(valueInput, { target: { value: "2" } });
    fireEvent.blur(valueInput);
    expect(onChange).toHaveBeenCalledWith({ a: "2" });

    // Simulate a fresh row started, not yet blurred...
    const addButton = screen.getByText("Add row");
    fireEvent.click(addButton);
    const keyInputs = screen.getAllByPlaceholderText("key");
    const draftKeyInput = keyInputs[keyInputs.length - 1] as HTMLInputElement;
    fireEvent.change(draftKeyInput, { target: { value: "in-progress" } });

    // ...then the PUT echoes back a *new object* that is deep-equal to what was emitted.
    rerender(<KeyValueListField label="Aliases" items={{ a: "2" }} onChange={onChange} />);
    expect((draftKeyInput as HTMLInputElement).value).toBe("in-progress");
  });
});

describe("KeyValueListField — invalid transient states", () => {
  it("does not emit and marks both rows when two rows share a key", () => {
    const onChange = vi.fn();
    render(<KeyValueListField label="Aliases" items={{ a: "1", b: "2" }} onChange={onChange} />);
    const { keyInput } = getRowInputs("b");
    fireEvent.change(keyInput, { target: { value: "a" } });
    fireEvent.blur(keyInput);
    expect(onChange).not.toHaveBeenCalled();
    expect(screen.getAllByText('Duplicate key "a".')).toHaveLength(2);
  });

  it("does not emit and keeps the row visible when a value has no key", () => {
    const onChange = vi.fn();
    render(<KeyValueListField label="Aliases" items={{ a: "1" }} onChange={onChange} />);
    const { keyInput, valueInput } = getRowInputs("a");
    fireEvent.change(keyInput, { target: { value: "" } });
    fireEvent.blur(keyInput);
    expect(onChange).not.toHaveBeenCalled();
    expect(screen.getByText("Needs a key.")).toBeTruthy();
    expect((valueInput as HTMLInputElement).value).toBe("1");
  });
});

describe("KeyValueListField — add/remove", () => {
  it("Add row appends a blank row without emitting", () => {
    const onChange = vi.fn();
    render(<KeyValueListField label="Aliases" items={{ a: "1" }} onChange={onChange} />);
    fireEvent.click(screen.getByText("Add row"));
    expect(onChange).not.toHaveBeenCalled();
    expect(screen.getAllByPlaceholderText("key")).toHaveLength(2);
  });

  it("Remove emits immediately with the row excluded", () => {
    const onChange = vi.fn();
    render(<KeyValueListField label="Aliases" items={{ a: "1", b: "2" }} onChange={onChange} />);
    const { keyInput } = getRowInputs("a");
    const removeButton = keyInput.closest("div")!.querySelector("button")!;
    fireEvent.click(removeButton);
    expect(onChange).toHaveBeenCalledWith({ b: "2" });
  });
});

describe("KeyValueListField — errorFor", () => {
  it("renders an external error for the matching row", () => {
    render(
      <KeyValueListField
        label="Aliases"
        items={{ python: "python" }}
        onChange={vi.fn()}
        errorFor={(key) => (key === "python" ? "Maps to itself." : null)}
      />,
    );
    expect(screen.getByText("Maps to itself.")).toBeTruthy();
  });
});
