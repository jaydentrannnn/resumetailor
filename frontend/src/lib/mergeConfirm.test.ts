import { describe, expect, it } from "vitest";
import { resumeIsEmpty } from "./mergeConfirm";

describe("resumeIsEmpty", () => {
  it("is true with no sections or only empty sections", () => {
    expect(resumeIsEmpty({ sections: [] })).toBe(true);
    expect(resumeIsEmpty({ sections: [{ entries: [] }, { entries: [] }] })).toBe(true);
  });

  it("is false while the resume has not loaded", () => {
    expect(resumeIsEmpty(null)).toBe(false);
    expect(resumeIsEmpty(undefined)).toBe(false);
  });

  it("is false once any section holds an entry", () => {
    expect(resumeIsEmpty({ sections: [{ entries: [] }, { entries: [{}] }] })).toBe(false);
  });
});
