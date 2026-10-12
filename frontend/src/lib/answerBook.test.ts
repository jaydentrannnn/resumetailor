import { describe, expect, it } from "vitest";
import type { SavedAnswer } from "../api";
import { answerSource, filterAnswers, sourceCounts } from "./answerBook";

const item = (source: string, kind: "answer" | "type" = "answer"): SavedAnswer => ({
  id: 1,
  label: "Q",
  answer: "A",
  ats: "",
  company: "",
  source,
  uses: 0,
  updated_at: "",
  kind,
});

describe("answerBook", () => {
  it("badges each source", () => {
    expect(answerSource(item("correction"))).toBe("you");
    expect(answerSource(item("edited"))).toBe("you");
    expect(answerSource(item("page"))).toBe("page");
    expect(answerSource(item("custom"))).toBe("custom");
    expect(answerSource(item("ai"))).toBe("ai");
    expect(answerSource(item("ai", "type"))).toBe("learned");
  });
  it("filters and counts by source", () => {
    const items = [item("page"), item("ai"), item("page"), item("ai", "type")];
    expect(filterAnswers(items, "page")).toHaveLength(2);
    expect(filterAnswers(items, "all")).toHaveLength(4);
    expect(sourceCounts(items)).toEqual([
      ["page", 2],
      ["ai", 1],
      ["learned", 1],
    ]);
  });
});
