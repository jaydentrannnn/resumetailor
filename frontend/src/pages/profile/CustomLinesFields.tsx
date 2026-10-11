import { customLineRows, withCustomValue, withoutCustomValue } from "../../lib/customLines";
import type { MasterResume } from "../../lib/resumeEdit";
import { useTemplateState } from "../../state/templateState";

/**
 * The active template's extra header lines (a street address, a tagline) that the
 * template import kept as editable lines. Rendered inside "Resume contact"; nothing
 * when the template has none. Clearing a line removes it from the page.
 */
export function CustomLinesFields({
  resume,
  setResume,
}: {
  resume: MasterResume;
  setResume: (resume: MasterResume) => void;
}) {
  const { info } = useTemplateState();
  const rows = customLineRows(resume, info?.profile.custom_fields ?? []);
  if (!rows.length) return null;
  return (
    <div className="mt-4 border-t border-line pt-4">
      <p className="text-xs font-medium text-ink-2">Other lines from your template</p>
      <div className="mt-2 grid gap-4 sm:grid-cols-2">
        {rows.map((row) => (
          <label key={row.key} className="text-sm">
            {row.label}
            <input
              className="field mt-1"
              value={row.value}
              placeholder="Left off the page"
              onChange={(e) =>
                setResume(withCustomValue(resume, row.key, row.label, e.target.value))
              }
            />
            {row.edited && row.value !== row.templateText && (
              <button
                type="button"
                className="mt-1 text-xs text-ink-muted underline hover:text-ink"
                onClick={() => setResume(withoutCustomValue(resume, row.key))}
              >
                Reset to “{row.templateText}”
              </button>
            )}
          </label>
        ))}
      </div>
    </div>
  );
}
