import type {
  BulletStyle,
  CurrentLayout,
  FieldEmphasis,
  SeparatorRow,
  TemplateAdjustments,
} from "../api";

export const MARGIN_SIDES = ["top", "bottom", "left", "right"] as const;

/** Separator rows in panel order, with their labels (`document/adjust_separators.py`). */
export const SEPARATOR_ROWS: { row: SeparatorRow; label: string }[] = [
  { row: "contact", label: "Contact info" },
  { row: "project_tech", label: "Project → tools" },
  { row: "tech_items", label: "Between tools" },
  { row: "project_link", label: "Before project link" },
  { row: "skills_items", label: "Between skills" },
  { row: "coursework", label: "Between courses" },
  { row: "dates", label: "Date range" },
];

type Choice = { value: string; label: string };

/** Separators between items and parts of a line (`template_style.SEPARATOR_CHOICES`). */
export const SEPARATOR_CHOICES: Choice[] = [
  { value: " | ", label: "|  Pipe" },
  { value: " • ", label: "•  Bullet" },
  { value: " · ", label: "·  Middle dot" },
  { value: " – ", label: "–  En dash" },
  { value: " — ", label: "—  Em dash" },
  { value: ", ", label: ",  Comma" },
  { value: " / ", label: "/  Slash" },
  { value: "; ", label: ";  Semicolon" },
];

/** Inside a date range (`template_style.DATE_SEPARATOR_CHOICES`). */
export const DATE_SEPARATOR_CHOICES: Choice[] = [
  { value: " - ", label: "Jan 2024 - Present" },
  { value: " – ", label: "Jan 2024 – Present" },
  { value: " — ", label: "Jan 2024 — Present" },
  { value: "–", label: "Jan 2024–Present" },
  { value: " to ", label: "Jan 2024 to Present" },
];

/** Bullet markers (`template_style.BULLET_GLYPHS`) and the no-marker choices. */
export const BULLET_CHOICES: Choice[] = [
  { value: "keep", label: "Keep the template's" },
  { value: "●", label: "●  Disc" },
  { value: "•", label: "•  Bullet" },
  { value: "◦", label: "◦  Circle" },
  { value: "▪", label: "▪  Small square" },
  { value: "■", label: "■  Square" },
  { value: "–", label: "–  Dash" },
  { value: "›", label: "›  Chevron" },
  { value: "➢", label: "➢  Arrow" },
  { value: "✓", label: "✓  Check" },
  { value: "none_indent", label: "None, indented" },
  { value: "none_flush", label: "None, flush left" },
];

/** `choices` for a select, with `current` added first when it is none of them (a
 * separator read off the template, say), so the select never shows the wrong value. */
export function withCurrent(choices: Choice[], current: string): Choice[] {
  if (choices.some((c) => c.value === current)) return choices;
  return [{ value: current, label: `“${current.trim() || current}” (current)` }, ...choices];
}

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
  const separators = Object.fromEntries(
    Object.entries(draft.separators).filter(
      ([row, value]) => value !== current.separators[row as SeparatorRow],
    ),
  );
  if (Object.keys(separators).length) adj.separators = separators;
  if (!sameBullets(draft.bullets, current.bullets)) adj.bullets = draft.bullets;
  if (
    draft.links &&
    current.links &&
    (draft.links.color !== current.links.color || draft.links.underline !== current.links.underline)
  ) {
    adj.links = draft.links;
  }
  return adj;
}

function sameBullets(a: BulletStyle, b: BulletStyle): boolean {
  return a.list === b.list && a.skills === b.skills;
}

export function hasAdjustments(adj: TemplateAdjustments): boolean {
  return Object.keys(adj).length > 0;
}

/** Whether applying `adj` changes how much fits on a page, so page fit is re-measured.
 * Bold or italic changes letter widths, so emphasis counts; the link look alone does not. */
export function changesFit(adj: TemplateAdjustments): boolean {
  return Boolean(
    adj.margins || adj.font_family || adj.font_size || adj.separators || adj.bullets || adj.fields,
  );
}

/** The name an applied adjustment installs under; adjusting again doesn't stack suffixes. */
export function adjustedLabel(active: string | null | undefined): string {
  const base = (active || "Template").replace(/(\s*\(adjusted\))+$/, "");
  return `${base} (adjusted)`;
}

/** Fields printed as links: their underline is the links row's, not their own. */
export const LINK_FIELDS = new Set(["LinkedIn", "GitHub", "Project link"]);

const inches = (n: number) => `${n}"`;

/** One line for a collapsed Margins header. */
export function marginsSummary(m: CurrentLayout["margins"]): string {
  const values = MARGIN_SIDES.map((side) => m[side]);
  if (values.every((v) => v === values[0])) return `${inches(values[0])} all sides`;
  if (m.top === m.bottom && m.left === m.right)
    return `${inches(m.top)} top/bottom · ${inches(m.left)} sides`;
  return MARGIN_SIDES.map((side) => `${side[0].toUpperCase()} ${inches(m[side])}`).join(" · ");
}

function bulletName(value: string): string {
  if (value === "keep") return "template's";
  if (value === "none_indent") return "none";
  if (value === "none_flush") return "none, flush";
  return value;
}

/** One line for a collapsed Bullet styles header. */
export function bulletsSummary(b: BulletStyle): string {
  return `Lists ${bulletName(b.list)} · Skills ${bulletName(b.skills)}`;
}

/** The separator rows this template prints, in panel order. */
export function printedSeparatorRows(draft: CurrentLayout) {
  return SEPARATOR_ROWS.filter(({ row }) => draft.separators[row] !== undefined);
}

/** How many separator rows differ from the template's. */
export function separatorsChanged(current: CurrentLayout, draft: CurrentLayout): number {
  return Object.entries(draft.separators).filter(
    ([row, value]) => value !== current.separators[row as SeparatorRow],
  ).length;
}

/** How many emphasis rows (and the links row) differ from the template's. */
export function emphasisChanged(current: CurrentLayout, draft: CurrentLayout): number {
  const before = new Map(current.fields.map((f) => [f.label, f]));
  const fields = draft.fields.filter((f) => {
    const was = before.get(f.label);
    return was && (["bold", "italic", "underline"] as const).some((k) => f[k] !== was[k]);
  }).length;
  const links =
    draft.links &&
    current.links &&
    (draft.links.color !== current.links.color || draft.links.underline !== current.links.underline)
      ? 1
      : 0;
  return fields + links;
}
