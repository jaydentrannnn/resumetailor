import type { TemplateUnmappedLine } from "../../api";
import { choiceFor, labelFor, type LineChoice, withChoice } from "../../lib/unmappedLines";
import { Segmented } from "../ui";

const CHOICES = [
  { id: "field", label: "Editable line" },
  { id: "static", label: "Keep as-is" },
  { id: "drop", label: "Remove" },
];

const HELP: Record<LineChoice, string> = {
  field: "You can change it under Profile › Personal; it shows on the resume and cover letter.",
  static: "Stays exactly as written in the template. Editing it means re-uploading.",
  drop: "Left out of the template.",
};

/**
 * Lines above the first section that the analyzer could not match to your name or a
 * contact field (a street address, a tagline). Each one can become an editable line,
 * stay frozen text, or be removed — written straight into the draft profile's
 * `custom_fields` / `dropped_paragraph_ids`.
 */
export function UnmappedLinesPanel({
  lines,
  profile,
  onChange,
}: {
  lines: TemplateUnmappedLine[];
  profile: Record<string, unknown>;
  onChange: (next: Record<string, unknown>) => void;
}) {
  if (!lines.length) return null;
  return (
    <section className="mt-6 border-t border-line pt-4" aria-labelledby="unmapped-lines-title">
      <h3 id="unmapped-lines-title" className="text-sm font-medium text-ink">
        Other lines in your header
      </h3>
      <p className="mt-1 text-xs text-ink-muted">
        These lines aren&apos;t your name or a contact detail. Choose what happens to each.
      </p>
      <ul className="mt-3 space-y-4">
        {lines.map((line) => {
          const choice = choiceFor(profile, line);
          return (
            <li key={line.paragraph_id} className="rounded-sm border border-line px-3 py-3">
              <p className="text-sm text-ink">“{line.text}”</p>
              <Segmented
                className="mt-2"
                label={`What to do with “${line.text}”`}
                items={CHOICES}
                value={choice}
                onChange={(id) => onChange(withChoice(profile, line, id as LineChoice))}
              />
              {choice === "field" && (
                <label className="mt-3 block text-sm">
                  <span className="mb-1.5 block text-xs font-medium text-ink-2">Field name</span>
                  <input
                    className="field max-w-xs"
                    value={labelFor(profile, line)}
                    onChange={(e) => onChange(withChoice(profile, line, "field", e.target.value))}
                  />
                </label>
              )}
              <p className="mt-2 text-xs text-ink-muted">{HELP[choice]}</p>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
