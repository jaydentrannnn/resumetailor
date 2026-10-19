// @vitest-environment jsdom
import { describe, expect, it } from "vitest";
import { editableElement, fieldHasSelection, textMenuItems } from "./textMenu";

describe("textMenuItems", () => {
  it("offers nothing on plain app chrome", () => {
    expect(textMenuItems({ editable: false, hasSelection: false })).toEqual([]);
  });

  it("offers Copy for selected page text", () => {
    expect(textMenuItems({ editable: false, hasSelection: true })).toEqual(["copy"]);
  });

  it("offers Paste and Select all in an empty selection of a field", () => {
    expect(textMenuItems({ editable: true, hasSelection: false })).toEqual(["paste", "selectAll"]);
  });

  it("offers every item for selected text in a field", () => {
    expect(textMenuItems({ editable: true, hasSelection: true })).toEqual([
      "cut",
      "copy",
      "paste",
      "selectAll",
    ]);
  });
});

describe("editableElement", () => {
  it("finds text fields and contenteditable, not buttons or read-only fields", () => {
    document.body.innerHTML = `
      <input id="text" type="text">
      <input id="box" type="checkbox">
      <input id="ro" type="text" readonly>
      <textarea id="area"></textarea>
      <div contenteditable="true"><span id="inner">x</span></div>
      <button id="btn">Go</button>`;
    const byId = (id: string) => document.getElementById(id);
    expect(editableElement(byId("text"))).toBe(byId("text"));
    expect(editableElement(byId("area"))).toBe(byId("area"));
    expect(editableElement(byId("inner"))).not.toBeNull();
    expect(editableElement(byId("box"))).toBeNull();
    expect(editableElement(byId("ro"))).toBeNull();
    expect(editableElement(byId("btn"))).toBeNull();
  });

  it("reads a field's own selection", () => {
    document.body.innerHTML = `<input id="f" type="text" value="hello">`;
    const field = document.getElementById("f") as HTMLInputElement;
    field.setSelectionRange(0, 0);
    expect(fieldHasSelection(field)).toBe(false);
    field.setSelectionRange(0, 3);
    expect(fieldHasSelection(field)).toBe(true);
  });
});
