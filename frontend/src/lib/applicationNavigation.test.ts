// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";
import { recallApplyParams, rememberApplyParams } from "./applicationNavigation";

afterEach(() => {
  vi.restoreAllMocks();
  window.sessionStorage.clear();
});

describe("remembered Apply params", () => {
  it("round-trips the tab, page and filters but not the settings drawer", () => {
    rememberApplyParams("ws-1", "tab=done&archive_page=2&settings=1&q=acme");
    expect(new URLSearchParams(recallApplyParams("ws-1")).toString()).toBe(
      "tab=done&archive_page=2&q=acme",
    );
    expect(recallApplyParams("ws-2")).toBe("");
  });

  it("falls back to memory when storage is blocked", () => {
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    rememberApplyParams("ws-3", "tab=progress");
    expect(recallApplyParams("ws-3")).toBe("tab=progress");
  });
});
