import { describe, expect, it } from "vitest";
import { countLabel } from "./countLabel";

describe("countLabel", () => {
  it("uses the singular for exactly one", () => {
    expect(countLabel(1, "bullet")).toBe("1 bullet");
    expect(countLabel(0, "bullet")).toBe("0 bullets");
    expect(countLabel(4, "skill")).toBe("4 skills");
  });

  it("takes an irregular plural", () => {
    expect(countLabel(2, "entry", "entries")).toBe("2 entries");
  });
});
