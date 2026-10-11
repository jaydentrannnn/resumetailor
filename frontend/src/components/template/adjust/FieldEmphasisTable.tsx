import type { FieldEmphasis, LinkLook } from "../../../api";
import { LINK_FIELDS } from "../../../lib/templateAdjust";
import { buttonClass } from "../../ui";

const MARKS = [
  { key: "bold", text: "B", name: "Bold", className: "font-bold" },
  { key: "italic", text: "I", name: "Italic", className: "italic" },
  { key: "underline", text: "U", name: "Underline", className: "underline" },
] as const;

const toggleClass = (on: boolean, extra = "") =>
  `${buttonClass(on ? "primary" : "plain", "sm")} w-8 ${extra}`.trim();

/** The links row: colour (an "A" over a blue bar, like a font-colour button) and
 * underline, sitting in the I and U columns so U lines up with every other row's U. */
function LinksRow({ links, onChange }: { links: LinkLook; onChange: (next: LinkLook) => void }) {
  const blue = links.color === "blue";
  return (
    <li className="flex items-center justify-between gap-3 py-1.5">
      <span className="min-w-0 truncate text-sm font-medium">All links</span>
      <span className="flex gap-1" role="group" aria-label="Link look">
        <span aria-hidden className="w-8" />
        <button
          type="button"
          aria-label="Blue links"
          aria-pressed={blue}
          title={blue ? "Blue links (on)" : "Links in the text colour"}
          onClick={() => onChange({ ...links, color: blue ? "text" : "blue" })}
          className={toggleClass(blue, "flex-col gap-0.5")}
        >
          <span className="leading-none">A</span>
          <span aria-hidden className="h-[3px] w-3.5 rounded-xs bg-doc-link" />
        </button>
        <button
          type="button"
          aria-label="Underline links"
          aria-pressed={links.underline}
          onClick={() => onChange({ ...links, underline: !links.underline })}
          className={toggleClass(links.underline, "underline")}
        >
          U
        </button>
      </span>
    </li>
  );
}

/**
 * One row per «field» in the template with bold / italic / underline toggles, and —
 * when the template prints links — a links row for their colour and underline. A link
 * field's own underline would be overruled by the links row, so it isn't offered.
 */
export function FieldEmphasisTable({
  fields,
  onChange,
  links,
  onLinksChange,
}: {
  fields: FieldEmphasis[];
  onChange: (next: FieldEmphasis[]) => void;
  links: LinkLook | null;
  onLinksChange: (next: LinkLook) => void;
}) {
  const toggle = (index: number, key: (typeof MARKS)[number]["key"]) =>
    onChange(fields.map((f, i) => (i === index ? { ...f, [key]: !f[key] } : f)));
  return (
    <>
      <p className="text-xs text-ink-muted">
        Applies to every entry: bolding Company bolds every company name.
        {links && " Links stay clickable whatever their look."}
      </p>
      <ul className="mt-2 divide-y divide-line">
        {links && <LinksRow links={links} onChange={onLinksChange} />}
        {fields.map((field, index) => (
          <li key={field.label} className="flex items-center justify-between gap-3 py-1.5">
            <span className="min-w-0 truncate text-sm">{field.label}</span>
            <span className="flex gap-1" role="group" aria-label={`${field.label} emphasis`}>
              {MARKS.map((mark) =>
                links && mark.key === "underline" && LINK_FIELDS.has(field.label) ? (
                  <span key={mark.key} aria-hidden className="w-8" />
                ) : (
                  <button
                    key={mark.key}
                    type="button"
                    aria-label={`${mark.name} ${field.label}`}
                    aria-pressed={field[mark.key]}
                    onClick={() => toggle(index, mark.key)}
                    className={toggleClass(field[mark.key], mark.className)}
                  >
                    {mark.text}
                  </button>
                ),
              )}
            </span>
          </li>
        ))}
      </ul>
    </>
  );
}
