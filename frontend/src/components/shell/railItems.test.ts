import { describe, expect, it } from "vitest";
import { windowTitle } from "../../lib/shell";
import { railTarget } from "./railItems";

const key = (k: string, extra: Partial<KeyboardEvent> = {}) =>
  ({
    key: k,
    ctrlKey: true,
    metaKey: false,
    altKey: false,
    shiftKey: false,
    ...extra,
  }) as KeyboardEvent;

describe("railTarget", () => {
  it("maps Ctrl/Cmd+1…5 to the rail's pages and Ctrl+, to Settings", () => {
    expect(railTarget(key("1"))).toBe("/");
    expect(railTarget(key("2"))).toBe("/applications");
    expect(railTarget(key("3"))).toBe("/resume");
    expect(railTarget(key("5", { ctrlKey: false, metaKey: true }))).toBe("/profile");
    expect(railTarget(key(","))).toBe("/settings");
  });

  it("ignores other keys and modifier mixes", () => {
    expect(railTarget(key("6"))).toBeNull();
    expect(railTarget(key("0"))).toBeNull();
    expect(railTarget(key("1", { ctrlKey: false }))).toBeNull();
    expect(railTarget(key("1", { shiftKey: true }))).toBeNull();
    expect(railTarget(key("1", { altKey: true }))).toBeNull();
  });
});

describe("windowTitle", () => {
  it("names the page and marks unsaved edits", () => {
    expect(windowTitle(null, false)).toBe("ResumeTailor");
    expect(windowTitle("Resume", false)).toBe("Resume — ResumeTailor");
    expect(windowTitle("Resume", true)).toBe("• Resume — ResumeTailor");
  });
});
