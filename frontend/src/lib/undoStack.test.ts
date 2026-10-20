import { describe, expect, it } from "vitest";
import type { MasterResume } from "./resumeEdit";
import {
  UNDO_LIMIT,
  describeChange,
  emptyStack,
  record,
  redo,
  restoreStructure,
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

describe("restoreStructure", () => {
  const bullet = (id: string, text: string) => ({ id, text, tags: [] });
  const job = (id: string, title: string, bullets: ReturnType<typeof bullet>[]) => ({
    id,
    company: "Acme",
    title,
    start: "2024-01",
    end: "Present",
    bullets,
  });
  const resume = (entries: ReturnType<typeof job>[]) =>
    ({
      contact: { name: "A", email: "a@b.c" },
      sections: [{ id: "exp", kind: "experience", title: "Experience", entries }],
    }) as unknown as MasterResume;

  it("brings back a deleted entry and keeps text edited after the delete", () => {
    const before = resume([job("e1", "Engineer", [bullet("b1", "old")]), job("e2", "Intern", [])]);
    const live = resume([job("e1", "Senior Engineer", [bullet("b1", "new")])]);
    const restored = restoreStructure(before, live);
    const entries = restored.sections[0].entries as ReturnType<typeof job>[];
    expect(entries.map((e) => e.id)).toEqual(["e1", "e2"]);
    expect(entries[0].title).toBe("Senior Engineer");
    expect(entries[0].bullets[0].text).toBe("new");
    expect(entries[1].title).toBe("Intern");
  });

  it("brings back a deleted bullet inside an entry whose text changed", () => {
    const before = resume([job("e1", "Engineer", [bullet("b1", "one"), bullet("b2", "two")])]);
    const live = resume([job("e1", "Lead", [bullet("b2", "two, edited")])]);
    const entry = restoreStructure(before, live).sections[0].entries[0] as ReturnType<typeof job>;
    expect(entry.title).toBe("Lead");
    expect(entry.bullets.map((b) => b.text)).toEqual(["one", "two, edited"]);
  });
});
