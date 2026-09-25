import { describe, expect, it } from "vitest";
import type { JobBullet } from "../api";
import {
  choiceFromRow,
  groupRows,
  initialReview,
  pendingCount,
  resetToAi,
  toRequest,
} from "./bulletReview";

const row = (id: string, over: Partial<JobBullet> = {}): JobBullet => ({
  bullet_id: id,
  section_title: "Experience",
  entry_label: "Analyst · Acme",
  source_text: `source ${id}`,
  ai_text: `ai ${id}`,
  current_text: `ai ${id}`,
  merged_from: [],
  ...over,
});

describe("bullet review state", () => {
  it("reads each bullet's saved choice back from the render", () => {
    expect(choiceFromRow(row("a")).mode).toBe("ai");
    expect(choiceFromRow(row("a", { current_text: null })).mode).toBe("remove");
    expect(choiceFromRow(row("a", { current_text: "source a" })).mode).toBe("original");
    expect(choiceFromRow(row("a", { current_text: "typed" }))).toEqual({
      mode: "edit",
      text: "typed",
    });
    // A merged bullet's "original" is several bullets, so its current text never equals one source.
    expect(
      choiceFromRow(row("m", { merged_from: ["m", "n"], current_text: "source m" })).mode,
    ).toBe("edit");
  });

  it("builds the request relative to the AI version and counts pending changes", () => {
    const rows = [row("a"), row("b"), row("c"), row("d")];
    const state = initialReview(rows);
    expect(pendingCount(rows, state)).toBe(0);
    state.a = { mode: "edit", text: "  new text " };
    state.b = { mode: "original", text: "" };
    state.c = { mode: "remove", text: "" };
    state.d = { mode: "edit", text: "ai d" }; // same as AI: not an edit
    expect(toRequest(state, rows, ["a"])).toEqual({
      edits: { a: "new text" },
      reverted: ["b"],
      removed: ["c"],
      confirmed: ["a"],
    });
    expect(pendingCount(rows, state)).toBe(4);
    expect(pendingCount(rows, resetToAi(rows))).toBe(0);
  });

  it("groups consecutive rows by entry", () => {
    const rows = [
      row("a"),
      row("b"),
      row("c", { entry_label: "Project X", section_title: "Projects" }),
    ];
    expect(groupRows(rows).map((g) => [g.entry, g.rows.length])).toEqual([
      ["Analyst · Acme", 2],
      ["Project X", 1],
    ]);
  });
});
