// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { LanguagesEditor } from "./LanguagesEditor";

// No `test.globals`, so Testing Library's automatic cleanup never registers.
afterEach(() => cleanup());

const english = { language: "English", fluent: true, levels: { Overall: "Native" } };

describe("LanguagesEditor", () => {
  it("adds a blank language", () => {
    const onChange = vi.fn();
    render(<LanguagesEditor languages={[]} onChange={onChange} />);
    fireEvent.click(screen.getByText("+ Add language"));
    expect(onChange).toHaveBeenCalledWith([{ language: "", fluent: false, levels: {} }]);
  });

  it("edits the name, fluency, and a category level", () => {
    const onChange = vi.fn();
    render(<LanguagesEditor languages={[english]} onChange={onChange} />);
    fireEvent.change(screen.getByDisplayValue("English"), { target: { value: "Vietnamese" } });
    expect(onChange).toHaveBeenLastCalledWith([{ ...english, language: "Vietnamese" }]);
    fireEvent.click(screen.getByLabelText("I am fluent in this language"));
    expect(onChange).toHaveBeenLastCalledWith([{ ...english, fluent: false }]);
    fireEvent.change(screen.getByLabelText("Reading"), { target: { value: "Advanced" } });
    expect(onChange).toHaveBeenLastCalledWith([
      { ...english, levels: { Overall: "Native", Reading: "Advanced" } },
    ]);
  });

  it("clears a level set back to Not set, and removes a row", () => {
    const onChange = vi.fn();
    render(<LanguagesEditor languages={[english]} onChange={onChange} />);
    fireEvent.change(screen.getByLabelText("Overall"), { target: { value: "" } });
    expect(onChange).toHaveBeenLastCalledWith([{ ...english, levels: {} }]);
    fireEvent.click(screen.getByText("Remove"));
    expect(onChange).toHaveBeenLastCalledWith([]);
  });
});
