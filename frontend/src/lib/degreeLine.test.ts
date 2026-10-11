import { describe, expect, it } from "vitest";
import { composeDegree, detectDegree, withDegreeParts, withDetectedParts } from "./degreeLine";

describe("composeDegree", () => {
  it.each([
    [
      ["B.A.", ["Business Administration"], ["Digital Information Systems"], "semicolon"],
      "B.A. in Business Administration; Minor in Digital Information Systems",
    ],
    [["B.S.", ["Math", "Physics"], [], "semicolon"], "B.S. in Math and Physics"],
    [
      ["B.S.", ["Math", "CS", "Physics"], ["Art", "Music"], "pipe"],
      "B.S. in Math, CS and Physics | Minors in Art and Music",
    ],
    [
      ["Bachelor of Arts", ["Economics"], ["Art"], "comma"],
      "Bachelor of Arts in Economics, Minor in Art",
    ],
    [["B.A.", [], [], "semicolon"], "B.A."],
    [["", ["Economics"], [" "], "semicolon"], "Economics"],
    [["", [], ["Art"], "semicolon"], "Minor in Art"],
  ] as const)("%j -> %s", (args, expected) => {
    const [kind, majors, minors, fmt] = args;
    expect(composeDegree(kind, [...majors], [...minors], fmt)).toBe(expected);
  });
});

describe("detectDegree", () => {
  it.each([
    [
      "B.A. in Business Administration; Minor in Digital Information Systems",
      ["B.A.", ["Business Administration"], ["Digital Information Systems"]],
    ],
    ["BS Computer Science | GPA: 3.9", ["BS", ["Computer Science"], []]],
    [
      "Bachelor of Science in Economics and Mathematics, Minors in Art and Music",
      ["Bachelor of Science", ["Economics", "Mathematics"], ["Art", "Music"]],
    ],
    ["Liberal Studies", ["", ["Liberal Studies"], []]],
  ] as const)("%s", (text, expected) => {
    expect(detectDegree(text)).toEqual(expected);
  });
});

describe("degree parts on an entry", () => {
  const base = { school: "U", degree: "B.A. in Economics; Minor in Art", dates: "" };

  it("keeps a manual line as typed", () => {
    const next = withDegreeParts({ ...base, degree_mode: "manual" as const }, { majors: ["Math"] });
    expect(next.degree).toBe(base.degree);
  });

  it("regenerates a generated line from its parts", () => {
    const next = withDegreeParts(
      { ...base, degree_mode: "generated" as const, degree_type: "B.S." },
      { majors: ["Math", "Physics"], minors: ["Art"], degree_format: "pipe" },
    );
    expect(next.degree).toBe("B.S. in Math and Physics | Minor in Art");
  });

  it("fills only blank parts from the typed line", () => {
    expect(withDetectedParts({ ...base, majors: ["Kept"] })).toMatchObject({
      degree_type: "B.A.",
      majors: ["Kept"],
      minors: ["Art"],
    });
  });
});
