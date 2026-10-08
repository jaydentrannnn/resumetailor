import type { SourceField } from "../../../api";
import type { suggestedEntries } from "../../../lib/onboarding";
import { FIELD_LABELS, SOURCE_FIELDS } from "../../../lib/sources";
/** Which job fields to search and the catalog sources that come with them, for review. */
export function JobSourcePicker({
  fields,
  onFields,
  suggestions,
  skipped,
  onToggle,
}: {
  fields: SourceField[];
  onFields: (next: SourceField[]) => void;
  suggestions: ReturnType<typeof suggestedEntries>;
  skipped: Set<string>;
  onToggle: (id: string) => void;
}) {
  return (
    <div className="space-y-4 border-t border-line pt-4">
      <fieldset>
        <legend className="text-sm font-semibold text-ink">Which jobs should we look for?</legend>
        <div className="mt-2 flex flex-wrap gap-2">
          {SOURCE_FIELDS.map((f) => (
            <label
              key={f}
              className={`flex cursor-pointer items-center gap-1.5 rounded-sm border px-3 py-1 text-xs ${
                fields.includes(f)
                  ? "border-selected-line bg-selected text-on-selected shadow-[inset_0_0_0_1px_var(--color-selected-line)]"
                  : "border-line bg-field"
              }`}
            >
              <input
                type="checkbox"
                checked={fields.includes(f)}
                onChange={(e) =>
                  onFields(e.target.checked ? [...fields, f] : fields.filter((x) => x !== f))
                }
              />
              {FIELD_LABELS[f]}
            </label>
          ))}
        </div>
      </fieldset>
      {suggestions.length === 0 ? (
        <p className="text-sm text-ink-muted">
          No job lists selected. You can add some later on the Applications page.
        </p>
      ) : (
        <fieldset>
          <legend className="text-sm font-medium text-ink">Job lists to search</legend>
          <ul className="mt-1 space-y-1">
            {suggestions.map((entry) => (
              <li key={entry.id}>
                <label className="flex items-start gap-2 text-sm">
                  <input
                    type="checkbox"
                    className="mt-1"
                    checked={!skipped.has(entry.id)}
                    onChange={() => onToggle(entry.id)}
                  />
                  <span>
                    {entry.name}
                    <span className="block text-xs text-ink-muted">{entry.description}</span>
                  </span>
                </label>
              </li>
            ))}
          </ul>
        </fieldset>
      )}
    </div>
  );
}
