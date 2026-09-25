import { describe, expect, it } from "vitest";
import { addBoard, hasBoard, newWatchlistSource, parseWords, removeBoard } from "./watchlist";

describe("watchlist helpers", () => {
  it("parses a comma list, trimming and dropping repeats", () => {
    expect(parseWords("analyst, intern,, Finance \nANALYST")).toEqual([
      "analyst",
      "intern",
      "Finance",
    ]);
    expect(parseWords("  ")).toEqual([]);
  });

  it("adds a board once, whatever the slug's case", () => {
    const acme = { ats: "greenhouse" as const, slug: "acme", company: "Acme" };
    const boards = addBoard([], acme);
    expect(addBoard(boards, { ...acme, slug: "ACME" })).toBe(boards);
    expect(addBoard(boards, { ...acme, ats: "lever" })).toHaveLength(2);
    expect(hasBoard(boards, { ...acme, company: "" })).toBe(true);
    expect(removeBoard(boards, acme)).toEqual([]);
  });

  it("starts a watchlist with a 7-day window and no boards", () => {
    const source = newWatchlistSource();
    expect(source.kind).toBe("ats_board");
    expect(source.boards).toEqual([]);
    expect(source.max_age_days).toBe(7);
    expect(source.include).toContain("analyst");
  });
});
