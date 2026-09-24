// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ChipListField } from "./ChipListField";

// Vitest isn't configured with `test.globals`, so Testing Library's automatic
// per-test cleanup never registers itself — see runState.test.tsx for the same note.
afterEach(() => cleanup());

/** ChipListField is fully controlled; wrap it in local state to test removal. */
function TestHarness({ initialItems }: { initialItems: string[] }) {
  const [items, setItems] = useState<string[]>(initialItems);
  return <ChipListField label="Verbs" items={items} onChange={setItems} />;
}

describe("ChipListField — normalize", () => {
  it("normalizes a committed token before storing it", () => {
    const onChange = vi.fn();
    render(
      <ChipListField
        label="Verbs"
        items={[]}
        onChange={onChange}
        normalize={(t) => t.trim().toLowerCase()}
      />,
    );
    const input = screen.getByLabelText("Verbs");
    fireEvent.change(input, { target: { value: "Administered" } });
    fireEvent.keyDown(input, { key: "Enter" });
    expect(onChange).toHaveBeenCalledWith(["administered"]);
  });

  it("normalizes before dedupe — a differently-cased duplicate is neither added nor reported as new", () => {
    const onChange = vi.fn();
    const onAddNew = vi.fn();
    render(
      <ChipListField
        label="Verbs"
        items={["administered"]}
        onChange={onChange}
        onAddNew={onAddNew}
        normalize={(t) => t.trim().toLowerCase()}
      />,
    );
    const input = screen.getByLabelText("Verbs");
    fireEvent.change(input, { target: { value: "ADMINISTERED" } });
    fireEvent.keyDown(input, { key: "Enter" });
    expect(onChange).not.toHaveBeenCalled();
    expect(onAddNew).not.toHaveBeenCalled();
  });

  it("applies normalize to items on render, so a mixed-case stored item displays normalized", () => {
    render(
      <ChipListField
        label="Verbs"
        items={["Administered"]}
        onChange={vi.fn()}
        normalize={(t) => t.trim().toLowerCase()}
      />,
    );
    expect(screen.getByText("administered")).toBeTruthy();
  });
});

describe("ChipListField — validate", () => {
  const validate = (t: string) => (/^[a-z]+$/.test(t) ? null : `"${t}" is invalid.`);

  it("rejects an invalid token, shows a message, and keeps the text in the draft", () => {
    const onChange = vi.fn();
    render(<ChipListField label="Verbs" items={[]} onChange={onChange} validate={validate} />);
    const input = screen.getByLabelText("Verbs") as HTMLInputElement;
    fireEvent.change(input, { target: { value: "re-factored" } });
    fireEvent.keyDown(input, { key: "Enter" });
    expect(onChange).not.toHaveBeenCalled();
    expect(input.value).toBe("re-factored");
    expect(screen.getByText('"re-factored" is invalid.')).toBeTruthy();
  });

  it("commits valid tokens from a mixed comma-separated batch and keeps only the rejected one in the draft", () => {
    const onChange = vi.fn();
    render(<ChipListField label="Verbs" items={[]} onChange={onChange} validate={validate} />);
    const input = screen.getByLabelText("Verbs") as HTMLInputElement;
    fireEvent.change(input, { target: { value: "administered, e-mailed, assessed" } });
    expect(onChange).toHaveBeenCalledWith(["administered", "assessed"]);
    expect(input.value).toBe("e-mailed");
  });
});

describe("ChipListField — separators", () => {
  it("splits on whitespace as well as commas when configured", () => {
    const onChange = vi.fn();
    render(<ChipListField label="Verbs" items={[]} onChange={onChange} separators={/[,\s]+/} />);
    const input = screen.getByLabelText("Verbs");
    fireEvent.change(input, { target: { value: "administered assessed charted" } });
    fireEvent.keyDown(input, { key: "Enter" });
    expect(onChange).toHaveBeenCalledWith(["administered", "assessed", "charted"]);
  });
});

describe("ChipListField — accessible name", () => {
  it("is reachable by its label when one is given", () => {
    render(<ChipListField label="Tags" items={[]} onChange={vi.fn()} />);
    expect(screen.getByLabelText("Tags")).toBeTruthy();
  });

  it("is reachable by ariaLabel when label is omitted", () => {
    render(<ChipListField ariaLabel="Verbs in build" items={[]} onChange={vi.fn()} />);
    expect(screen.getByLabelText("Verbs in build")).toBeTruthy();
  });
});

describe("ChipListField — default behavior unchanged when normalize/validate/separators are omitted", () => {
  it("commits raw comma-separated tokens exactly as typed", () => {
    const onChange = vi.fn();
    render(<ChipListField label="Tags" items={[]} onChange={onChange} />);
    const input = screen.getByLabelText("Tags");
    fireEvent.change(input, { target: { value: "Python, JavaScript" } });
    expect(onChange).toHaveBeenCalledWith(["Python", "JavaScript"]);
  });

  it("Backspace on an empty draft removes the last chip", () => {
    render(<TestHarness initialItems={["a", "b"]} />);
    const input = screen.getByLabelText("Verbs");
    fireEvent.keyDown(input, { key: "Backspace" });
    expect(screen.queryByText("b")).toBeNull();
    expect(screen.getByText("a")).toBeTruthy();
  });
});
