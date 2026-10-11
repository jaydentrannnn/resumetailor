import type { CurrentLayout, FieldEmphasis, TemplateAdjustments } from "../api";

/** Fonts offered in Quick adjustments: installed with Word on Windows and macOS. */
export const FONT_CHOICES = [
  "Arial",
  "Calibri",
  "Cambria",
  "Garamond",
  "Georgia",
  "Helvetica",
  "Times New Roman",
  "Verdana",
];

export const MARGIN_SIDES = ["top", "bottom", "left", "right"] as const;

/** Only what changed from `current`, so an untouched setting is never rewritten. */
export function toAdjustments(current: CurrentLayout, draft: CurrentLayout): TemplateAdjustments {
  const adj: TemplateAdjustments = {};
  if (MARGIN_SIDES.some((side) => draft.margins[side] !== current.margins[side])) {
    adj.margins = draft.margins;
  }
  if (draft.font_family.trim() && draft.font_family !== current.font_family) {
    adj.font_family = draft.font_family.trim();
  }
  if (draft.font_size !== current.font_size) adj.font_size = draft.font_size;
  const before = new Map(current.fields.map((f) => [f.label, f]));
  const fields = draft.fields.flatMap((field) => {
    const was = before.get(field.label);
    if (!was) return [];
    const changed: Partial<FieldEmphasis> = { label: field.label };
    for (const key of ["bold", "italic", "underline"] as const) {
      if (field[key] !== was[key]) changed[key] = field[key];
    }
    return Object.keys(changed).length > 1 ? [changed] : [];
  });
  if (fields.length) adj.fields = fields;
  return adj;
}

export function hasAdjustments(adj: TemplateAdjustments): boolean {
  return Object.keys(adj).length > 0;
}
