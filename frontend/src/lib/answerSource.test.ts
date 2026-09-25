import { describe, expect, it } from "vitest";
import { answerSourceLabel } from "./answerSource";

describe("answerSourceLabel", () => {
  it("names known sources and falls back to spaced words", () => {
    expect(answerSourceLabel("memory")).toBe("Answered from your saved answer");
    expect(answerSourceLabel("some_new_source")).toBe("some new source");
  });
});
