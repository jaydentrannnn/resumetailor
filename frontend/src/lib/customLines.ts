import type { TemplateCustomField } from "../api";
import type { MasterResume } from "./resumeEdit";

/** One editable extra line: the active template's slot joined with the resume's value. */
export type CustomLineRow = {
  key: string;
  label: string;
  /** What prints: the resume's value, else the template's own text. */
  value: string;
  /** The line as uploaded; printed whenever the resume has no value of its own. */
  templateText: string;
  /** The resume holds its own value (so "Reset" can restore the template text). */
  edited: boolean;
};

/** Rows for every custom line the active template has, in template order. */
export function customLineRows(
  resume: MasterResume,
  slots: TemplateCustomField[],
): CustomLineRow[] {
  const values = new Map((resume.custom_fields ?? []).map((f) => [f.key, f]));
  return slots.map((slot) => {
    const own = values.get(slot.key);
    return {
      key: slot.key,
      label: slot.label,
      value: own ? (own.value ?? "") : slot.text,
      templateText: slot.text,
      edited: own !== undefined,
    };
  });
}

/** `resume` with line `key` set to `value` ("" removes the line from the page). */
export function withCustomValue(
  resume: MasterResume,
  key: string,
  label: string,
  value: string,
): MasterResume {
  const others = (resume.custom_fields ?? []).filter((f) => f.key !== key);
  return { ...resume, custom_fields: [...others, { key, label, value }] };
}

/** `resume` without its own value for `key`, so the template's text prints again. */
export function withoutCustomValue(resume: MasterResume, key: string): MasterResume {
  return { ...resume, custom_fields: (resume.custom_fields ?? []).filter((f) => f.key !== key) };
}
