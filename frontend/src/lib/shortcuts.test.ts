// @vitest-environment jsdom
import { describe, expect, it } from "vitest";
import { shortcutFor } from "./shortcuts";

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
});
