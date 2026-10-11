import { describe, expect, it } from "vitest";
import type { CurrentLayout } from "../api";
import {
  adjustedLabel,
  BULLET_CHOICES,
  changesFit,
  hasAdjustments,
  toAdjustments,
  withCurrent,
} from "./templateAdjust";

const current: CurrentLayout = {
  margins: { top: 1, bottom: 1, left: 1, right: 1 },
  font_family: "Calibri",
  font_size: 11,
  fields: [
    { label: "Company", bold: true, italic: false, underline: false },
    { label: "Job title", bold: false, italic: false, underline: false },
  ],
  separators: { contact: " • ", tech_items: ", " },
  bullets: { list: "keep", skills: "keep" },
  links: { color: "blue", underline: true },
};

it("sends nothing when nothing changed", () => {
  expect(hasAdjustments(toAdjustments(current, structuredClone(current)))).toBe(false);
});

it("sends only the changed settings and field properties", () => {
  const draft = structuredClone(current);
  draft.margins.left = 0.5;
  draft.font_size = 10.5;
  draft.fields[1].italic = true;
  expect(toAdjustments(current, draft)).toEqual({
    margins: { top: 1, bottom: 1, left: 0.5, right: 1 },
    font_size: 10.5,
    fields: [{ label: "Job title", italic: true }],
  });
});

it("sends only the separator rows that changed, and whole bullet and link choices", () => {
  const draft = structuredClone(current);
  draft.separators.tech_items = " / ";
  draft.bullets.skills = "none_flush";
  draft.links = { color: "text", underline: true };
  expect(toAdjustments(current, draft)).toEqual({
    separators: { tech_items: " / " },
    bullets: { list: "keep", skills: "none_flush" },
    links: { color: "text", underline: true },
  });
});

it("ignores a blank font name", () => {
  expect(toAdjustments(current, { ...current, font_family: "  " })).toEqual({});
});

it("re-measures page fit unless only the link look changed", () => {
  expect(changesFit({ links: { color: "text", underline: false } })).toBe(false);
  expect(changesFit({ separators: { tech_items: " / " } })).toBe(true);
  expect(changesFit({ fields: [{ label: "Company", bold: false }] })).toBe(true);
});

it("lists a value read off the template that is none of the choices", () => {
  const choices = withCurrent(BULLET_CHOICES, "❖");
  expect(choices[0]).toEqual({ value: "❖", label: "“❖” (current)" });
  expect(withCurrent(BULLET_CHOICES, "keep")).toBe(BULLET_CHOICES);
});

describe("adjustedLabel", () => {
  it("adds the suffix once", () => {
    expect(adjustedLabel("Nina")).toBe("Nina (adjusted)");
    expect(adjustedLabel("Nina (adjusted)")).toBe("Nina (adjusted)");
    expect(adjustedLabel("Nina (adjusted) (adjusted)")).toBe("Nina (adjusted)");
    expect(adjustedLabel("")).toBe("Template (adjusted)");
  });
});
