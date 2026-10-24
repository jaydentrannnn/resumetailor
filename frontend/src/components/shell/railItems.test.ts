import { describe, expect, it } from "vitest";
import { windowTitle } from "../../lib/shell";
import { railTarget, visibleRailItems } from "./railItems";

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
  it("maps Ctrl/Cmd+1…6 to the rail's pages and Ctrl+, to Settings", () => {
    expect(railTarget(key("1"))).toBe("/");
    expect(railTarget(key("2"))).toBe("/applications");
    expect(railTarget(key("3"))).toBe("/tracker");
    expect(railTarget(key("4"))).toBe("/resume");
    expect(railTarget(key("6", { ctrlKey: false, metaKey: true }))).toBe("/profile");
    expect(railTarget(key(","))).toBe("/settings");
  });

  it("ignores other keys and modifier mixes", () => {
    expect(railTarget(key("7"))).toBeNull();
    expect(railTarget(key("0"))).toBeNull();
    expect(railTarget(key("1", { ctrlKey: false }))).toBeNull();
    expect(railTarget(key("1", { shiftKey: true }))).toBeNull();
    expect(railTarget(key("1", { altKey: true }))).toBeNull();
  });

  it("follows a custom visible order", () => {
    const items = visibleRailItems({
      order: ["/profile", "/"],
      hidden: ["/applications", "/resume", "/template", "/tracker"],
    });
    expect(items.map((i) => i.to)).toEqual(["/profile", "/"]);
    expect(railTarget(key("1"), items)).toBe("/profile");
    expect(railTarget(key("2"), items)).toBe("/");
  });

  it("adds a new required page to the end of an older saved order", () => {
    const items = visibleRailItems({ order: ["/profile", "/"], hidden: [] });
    expect(items.map((i) => i.to)).toEqual([
      "/profile",
      "/",
      "/applications",
      "/tracker",
      "/resume",
      "/template",
    ]);
  });
});

describe("visibleRailItems", () => {
  it("hides optional pages until pinned and never empties the rail", () => {
    expect(visibleRailItems().map((i) => i.to)).not.toContain("/vocabulary");
    const pinned = visibleRailItems({
      order: ["/", "/vocabulary"],
      hidden: ["/applications", "/resume", "/template", "/profile", "/tracker"],
    });
    expect(pinned.map((i) => i.to)).toEqual(["/", "/vocabulary"]);
    expect(
      visibleRailItems({
        order: [],
        hidden: ["/", "/applications", "/resume", "/template", "/profile", "/tracker"],
      }).length,
    ).toBeGreaterThan(0);
  });
});

describe("windowTitle", () => {
  it("names the page and marks unsaved edits", () => {
    expect(windowTitle(null, false)).toBe("ResumeTailor");
    expect(windowTitle("Resume", false)).toBe("Resume — ResumeTailor");
    expect(windowTitle("Resume", true)).toBe("• Resume — ResumeTailor");
  });
});
