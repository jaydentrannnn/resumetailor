// @vitest-environment jsdom
import { describe, expect, it } from "vitest";
import { shortcutFor, undoKeyFor } from "./shortcuts";

const key = (k: string, extra: Partial<KeyboardEvent> = {}, target: EventTarget | null = null) =>
  ({ key: k, ctrlKey: false, metaKey: false, altKey: false, target, ...extra }) as KeyboardEvent;

describe("shortcutFor", () => {
  it("maps keys to actions outside text fields", () => {
    expect(shortcutFor(key("/"))).toBe("search");
    expect(shortcutFor(key("?"))).toBe("help");
    expect(shortcutFor(key("a"))).toBeNull();
  });
  it("lets Ctrl/Cmd+Enter through while typing, but not / and ?", () => {
    const textarea = document.createElement("textarea");
    expect(shortcutFor(key("Enter", { ctrlKey: true }, textarea))).toBe("primary");
    expect(shortcutFor(key("Enter", { metaKey: true }, textarea))).toBe("primary");
    expect(shortcutFor(key("/", {}, textarea))).toBeNull();
    expect(shortcutFor(key("?", {}, document.createElement("input")))).toBeNull();
    expect(shortcutFor(key("Enter"))).toBeNull();
  });
  it("maps Ctrl/Cmd+P to print, even while typing", () => {
    const input = document.createElement("input");
    expect(shortcutFor(key("p", { ctrlKey: true }, input))).toBe("print");
    expect(shortcutFor(key("P", { metaKey: true }))).toBe("print");
    expect(shortcutFor(key("p", { ctrlKey: true, shiftKey: true }))).toBeNull();
    expect(shortcutFor(key("p"))).toBeNull();
  });
  it("maps Ctrl/Cmd+S and F to save and find, even while typing", () => {
    const input = document.createElement("input");
    expect(shortcutFor(key("s", { ctrlKey: true }, input))).toBe("save");
    expect(shortcutFor(key("f", { metaKey: true }))).toBe("find");
    expect(shortcutFor(key("k", { ctrlKey: true }, input))).toBe("commands");
    expect(shortcutFor(key("s", { ctrlKey: true, altKey: true }))).toBeNull();
  });
});

describe("undoKeyFor", () => {
  it("undoes and redoes outside text fields only", () => {
    expect(undoKeyFor(key("z", { ctrlKey: true }))).toBe("undo");
    expect(undoKeyFor(key("Z", { ctrlKey: true, shiftKey: true }))).toBe("redo");
    expect(undoKeyFor(key("y", { metaKey: true }))).toBe("redo");
    expect(undoKeyFor(key("z"))).toBeNull();
    expect(undoKeyFor(key("z", { ctrlKey: true }, document.createElement("textarea")))).toBeNull();
  });
});
