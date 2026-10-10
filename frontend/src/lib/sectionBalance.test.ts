import { describe, expect, it } from "vitest";
import type { IncludeOptions, ResumeOutline } from "../api";
import {
  activeSections,
  evenWeights,
  fromShares,
  moveDivider,
  setDivider,
  toShares,
} from "./sectionBalance";

const sec = (id: string, kind = "experience") => ({ id, title: id.toUpperCase(), kind });
const sum = (xs: number[]) => xs.reduce((a, b) => a + b, 0);

const include: IncludeOptions = {
  contact_fields: null,
  gpa: true,
  coursework: true,
  exclude_entries: [],
  exclude_sections: [],
  exclude_experience: [],
  exclude_projects: [],
  section_order: null,
};

const outline = {
  sections: [
    {
      id: "work",
      title: "Work",
      kind: "experience",
      entries: [{ id: "a", label: "A", bullets: 3 }],
    },
    {
      id: "edu",
      title: "Education",
      kind: "education",
      entries: [{ id: "u", label: "U", bullets: 0 }],
    },
    { id: "lab", title: "Lab", kind: "experience", entries: [{ id: "b", label: "B", bullets: 2 }] },
    {
      id: "proj",
      title: "Projects",
      kind: "project",
      entries: [{ id: "p", label: "P", bullets: 4 }],
    },
    {
      id: "empty",
      title: "Empty",
      kind: "experience",
      entries: [{ id: "e", label: "E", bullets: 0 }],
    },
  ],
  sections_enabled: { projects: true },
  section_mode: "generic",
} as unknown as ResumeOutline;

describe("activeSections", () => {
  it("keeps experience/project sections with bullets, in the run's order", () => {
    const ids = activeSections(outline, { ...include, section_order: ["proj"] }).map((s) => s.id);
    expect(ids).toEqual(["proj", "work", "lab"]);
  });

  it("ignores Include's order under a fixed template, which prints the resume's order", () => {
    const fixed = { ...outline, section_mode: "fixed" } as ResumeOutline;
    const ids = activeSections(fixed, { ...include, section_order: ["proj"] }).map((s) => s.id);
    expect(ids).toEqual(["work", "lab", "proj"]);
  });

  it("drops unticked sections, sections whose entries are all excluded, and disabled projects", () => {
    const ids = (o: ResumeOutline, inc: Partial<IncludeOptions>) =>
      activeSections(o, { ...include, ...inc }).map((s) => s.id);
    expect(ids(outline, { exclude_sections: ["lab"] })).toEqual(["work", "proj"]);
    expect(ids(outline, { exclude_entries: ["a"] })).toEqual(["lab", "proj"]);
    expect(ids({ ...outline, sections_enabled: { projects: false } }, {})).toEqual(["work", "lab"]);
  });
});

describe("toShares", () => {
  it.each([2, 3, 6, 7, 20])("sums to 100 in 5%% steps with %i sections", (n) => {
    const active = Array.from({ length: n }, (_, i) => sec(`s${i}`));
    const shares = toShares(active, null);
    expect(sum(shares)).toBe(100);
    expect(shares.every((s) => s % 5 === 0 && s >= 5)).toBe(true);
  });

  it("follows relative weights and gives a missing section the mean", () => {
    expect(toShares([sec("a"), sec("b"), sec("c")], { a: 2, b: 1, c: 1 })).toEqual([50, 25, 25]);
    expect(toShares([sec("a"), sec("b"), sec("c")], { a: 3, b: 1 })).toEqual([50, 15, 35]);
  });

  it("never drops a section below 5%", () => {
    expect(toShares([sec("a"), sec("b")], { a: 1, b: 0 })).toEqual([95, 5]);
  });

  it("converts the legacy experience share across both groups", () => {
    const active = [sec("work"), sec("lab"), sec("proj", "project")];
    expect(toShares(active, null, 0.6)).toEqual([30, 30, 40]);
    expect(toShares([sec("a"), sec("b")], null, 0.6)).toEqual([50, 50]);
  });
});

describe("moveDivider", () => {
  it("changes only the two neighbours", () => {
    expect(moveDivider([40, 30, 30], 1, 10)).toEqual([40, 40, 20]);
    expect(moveDivider([40, 30, 30], 0, -12)).toEqual([30, 40, 30]);
  });

  it("clamps so each neighbour keeps 5%", () => {
    expect(moveDivider([40, 30, 30], 0, 50)).toEqual([65, 5, 30]);
    expect(moveDivider([40, 30, 30], 0, -50)).toEqual([5, 65, 30]);
    const same = [5, 95];
    expect(moveDivider(same, 0, -5)).toBe(same);
  });

  it("positions a divider from a pointer percentage", () => {
    expect(setDivider([40, 30, 30], 1, 52)).toEqual([40, 10, 50]);
  });
});

describe("fromShares", () => {
  it("keeps inactive sections' weights so re-ticking restores them", () => {
    const stored = { a: 50, b: 25, c: 25 };
    const edited = fromShares([sec("a"), sec("b")], [60, 40], stored);
    expect(edited).toEqual({ a: 45, b: 30, c: 25 });
    expect(toShares([sec("a"), sec("b"), sec("c")], edited)).toEqual([45, 30, 25]);
  });

  it("starts from percentages when nothing is stored", () => {
    expect(fromShares([sec("a"), sec("b")], [70, 30], null)).toEqual({ a: 70, b: 30 });
    expect(evenWeights([sec("a"), sec("b")])).toEqual({ a: 1, b: 1 });
  });
});
