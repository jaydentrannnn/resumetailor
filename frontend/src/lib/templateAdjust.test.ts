import { expect, it } from "vitest";
import type { CurrentLayout } from "../api";
import { hasAdjustments, toAdjustments } from "./templateAdjust";

const current: CurrentLayout = {
  margins: { top: 1, bottom: 1, left: 1, right: 1 },
  font_family: "Calibri",
  font_size: 11,
  fields: [
    { label: "Company", bold: true, italic: false, underline: false },
    { label: "Job title", bold: false, italic: false, underline: false },
  ],
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

it("ignores a blank font name", () => {
  expect(toAdjustments(current, { ...current, font_family: "  " })).toEqual({});
});
