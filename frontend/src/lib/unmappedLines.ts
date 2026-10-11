import type { TemplateUnmappedLine } from "../api";

/** What the template does with one unmapped line. */
export type LineChoice = "field" | "static" | "drop";

type Slot = { key: string; label: string; paragraph_id: number; text: string };
type Profile = Record<string, unknown>;

function slots(profile: Profile): Slot[] {
  return (profile.custom_fields as Slot[] | undefined) ?? [];
}

function dropped(profile: Profile): number[] {
  return (profile.dropped_paragraph_ids as number[] | undefined) ?? [];
}

/** The line's current choice in the draft profile. */
export function choiceFor(profile: Profile, line: TemplateUnmappedLine): LineChoice {
  if (slots(profile).some((s) => s.paragraph_id === line.paragraph_id)) return "field";
  if (dropped(profile).includes(line.paragraph_id)) return "drop";
  return "static";
}

/** The label of the line's custom field, or its suggestion when it is not one. */
export function labelFor(profile: Profile, line: TemplateUnmappedLine): string {
  return (
    slots(profile).find((s) => s.paragraph_id === line.paragraph_id)?.label ??
    line.suggested_label
  );
}

/** A `CUSTOM_KEY_PATTERN` slug for `label` ("Street address" -> "street_address"). */
export function keyFor(label: string): string {
  let slug = label
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/^_+|_+$/g, "")
    .slice(0, 32);
  if (!slug || !/^[a-z]/.test(slug)) slug = slug ? `line_${slug}` : "line";
  return slug;
}

function uniqueKey(label: string, taken: Set<string>): string {
  const base = keyFor(label);
  let key = base;
  for (let n = 2; taken.has(key); n++) key = `${base}_${n}`;
  return key;
}

/** `profile` with `line` set to `choice` (and, for a field, labelled `label`). */
export function withChoice(
  profile: Profile,
  line: TemplateUnmappedLine,
  choice: LineChoice,
  label = labelFor(profile, line),
): Profile {
  const others = slots(profile).filter((s) => s.paragraph_id !== line.paragraph_id);
  const otherDrops = dropped(profile).filter((id) => id !== line.paragraph_id);
  const taken = new Set(others.map((s) => s.key));
  const custom_fields =
    choice === "field"
      ? [
          ...others,
          {
            key: uniqueKey(label.trim() || line.suggested_label, taken),
            label,
            paragraph_id: line.paragraph_id,
            text: line.text,
          },
        ].sort((a, b) => a.paragraph_id - b.paragraph_id)
      : others;
  const dropped_paragraph_ids =
    choice === "drop" ? [...otherDrops, line.paragraph_id].sort((a, b) => a - b) : otherDrops;
  return { ...profile, custom_fields, dropped_paragraph_ids };
}
