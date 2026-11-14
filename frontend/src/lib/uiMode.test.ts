import { describe, expect, it } from "vitest";
import { hiddenInSimple, isSimple, revealedIds } from "./uiMode";

describe("uiMode", () => {
  it("is Full unless the server said Simple", () => {
    expect(isSimple({})).toBe(false);
    expect(isSimple({ ui_mode: "full" })).toBe(false);
    expect(isSimple({ ui_mode: "simple" })).toBe(true);
  });

  it("hides a block only in Simple and only when nothing keeps it", () => {
    expect(hiddenInSimple(false)).toBe(false);
    expect(hiddenInSimple(true)).toBe(true);
    expect(hiddenInSimple(true, true)).toBe(false);
  });

  it("reads the ids a link revealed", () => {
    expect([...revealedIds("?reveal=nightly, auto-submit")]).toEqual(["nightly", "auto-submit"]);
    expect(revealedIds("?tab=done").size).toBe(0);
  });
});
