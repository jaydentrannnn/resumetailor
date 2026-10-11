import type { FieldEmphasis } from "../../../api";
import { buttonClass } from "../../ui";

const MARKS = [
  { key: "bold", text: "B", name: "Bold", className: "font-bold" },
  { key: "italic", text: "I", name: "Italic", className: "italic" },
  { key: "underline", text: "U", name: "Underline", className: "underline" },
] as const;

/** One row per «field» in the template, with bold / italic / underline toggles. */
export function FieldEmphasisTable({
  fields,
  onChange,
}: {
  fields: FieldEmphasis[];
  onChange: (next: FieldEmphasis[]) => void;
}) {
  const toggle = (index: number, key: (typeof MARKS)[number]["key"]) =>
    onChange(fields.map((f, i) => (i === index ? { ...f, [key]: !f[key] } : f)));
  return (
    <section>
      <h3 className="text-xs font-medium text-ink-2">Field emphasis</h3>
      <p className="mt-1 text-xs text-ink-muted">
        Applies to every entry: bolding Company bolds every company name.
      </p>
      <ul className="mt-2 divide-y divide-line">
        {fields.map((field, index) => (
          <li key={field.label} className="flex items-center justify-between gap-3 py-1.5">
            <span className="min-w-0 truncate">{field.label}</span>
            <span className="flex gap-1" role="group" aria-label={`${field.label} emphasis`}>
              {MARKS.map((mark) => (
                <button
                  key={mark.key}
                  type="button"
                  aria-label={`${mark.name} ${field.label}`}
                  aria-pressed={field[mark.key]}
                  onClick={() => toggle(index, mark.key)}
                  className={`${buttonClass(field[mark.key] ? "primary" : "plain", "sm")} w-8 ${mark.className}`}
                >
                  {mark.text}
                </button>
              ))}
            </span>
          </li>
        ))}
      </ul>
    </section>
  );
}
