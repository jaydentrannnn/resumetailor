import { describe, expect, it } from "vitest";
import type { MasterResume } from "./resumeEdit";
import {
  UNDO_LIMIT,
  describeChange,
  emptyStack,
  record,
  redo,
  structureKey,
  undo,
} from "./undoStack";

describe("undo stack", () => {
  it("undoes and redoes in order, and a new change drops redo", () => {
    let stack = record(record(emptyStack<number>(), 1, "one"), 2, "two");
    const back = undo(stack, 3)!;
    expect(back.step).toEqual({ snapshot: 2, label: "two" });
    stack = back.stack;
    const again = redo(stack, 2)!;
    expect(again.step).toEqual({ snapshot: 3, label: "two" });
    stack = record(back.stack, 2, "other");
    expect(redo(stack, 9)).toBeNull();
    expect(undo(emptyStack<number>(), 0)).toBeNull();
  });

  it("keeps at most the last UNDO_LIMIT steps", () => {
    let stack = emptyStack<number>();
    for (let i = 0; i < UNDO_LIMIT + 5; i++) stack = record(stack, i, `step ${i}`);
    expect(stack.past).toHaveLength(UNDO_LIMIT);
    expect(stack.past[0].snapshot).toBe(5);
  });
});

const resume = (sections: MasterResume["sections"]) =>
  ({ contact: { name: "", email: "" }, sections }) as MasterResume;

const job = (id: string, bullets: string[], company = "Acme") =>
  ({ id, company, bullets: bullets.map((b) => ({ id: b, text: "" })) }) as never;

describe("structureKey", () => {
  const base = resume([
    { id: "exp", title: "Experience", kind: "experience", entries: [job("a", ["a1", "a2"])] },
  ]);

  it("ignores typing but sees adds and moves", () => {
    const typed = resume([
      {
        id: "exp",
        title: "Work",
        kind: "experience",
        entries: [job("a", ["a1", "a2"], "Acme Corp")],
      },
    ]);
    expect(structureKey(typed)).toBe(structureKey(base));
    const moved = resume([
      { id: "exp", title: "Experience", kind: "experience", entries: [job("a", ["a2", "a1"])] },
    ]);
    expect(structureKey(moved)).not.toBe(structureKey(base));
  });

  it("names unlabelled changes", () => {
    const added = resume([
      {
        id: "exp",
        title: "Experience",
        kind: "experience",
        entries: [job("a", ["a1", "a2"]), job("b", [])],
      },
    ]);
    expect(describeChange(base, added)).toBe("Added an entry");
    const bullet = resume([
      {
        id: "exp",
        title: "Experience",
        kind: "experience",
        entries: [job("a", ["a1", "a2", "a3"])],
      },
    ]);
    expect(describeChange(base, bullet)).toBe("Added a bullet");
    expect(describeChange(added, base)).toBe("Removed an item");
  });
});
