import type { CoverLetterField, CoverLetterSettings } from "../../../api";
import { letterheadShows, withLetterheadField } from "../../../lib/coverLetterSettings";
import { Segmented } from "../../ui";

const MODES = [
  { id: "same_as_resume", label: "Same as resume" },
  { id: "custom", label: "Choose lines" },
];

/** Letterhead: the resume header's lines, or a chosen subset. Your name always prints. */
export function LetterheadOptions({
  settings,
  fields,
  onChange,
}: {
  settings: CoverLetterSettings;
  fields: CoverLetterField[];
  onChange: (next: CoverLetterSettings) => void;
}) {
  const custom = settings.letterhead === "custom";
  const seeded = () => fields.filter((f) => f.has_value).map((f) => f.id);
  return (
    <div>
      <Segmented
        label="Letterhead lines"
        items={MODES}
        value={settings.letterhead}
        onChange={(mode) =>
          onChange(
            mode === "custom"
              ? {
                  ...settings,
                  letterhead: "custom",
                  letterhead_fields: settings.letterhead_fields.length
                    ? settings.letterhead_fields
                    : seeded(),
                }
              : { ...settings, letterhead: "same_as_resume" },
          )
        }
      />
      <fieldset className="mt-3 space-y-1.5">
        <legend className="sr-only">Lines in the letterhead</legend>
        {fields.map((field) => (
          <label key={field.id} className="flex items-center gap-2">
            <input
              type="checkbox"
              checked={letterheadShows(settings, field)}
              disabled={!field.has_value}
              onChange={(e) =>
                onChange(withLetterheadField(settings, fields, field.id, e.target.checked))
              }
            />
            <span className={field.has_value ? "" : "text-ink-muted"}>{field.label}</span>
            {!field.has_value && <span className="text-xs text-ink-muted">(empty)</span>}
          </label>
        ))}
      </fieldset>
      <p className="mt-2 text-xs text-ink-muted">
        {custom
          ? "Only the ticked lines print under your name."
          : "Shows what your resume header shows. Untick a line to choose your own."}{" "}
        Edit the values under Profile › Personal.
      </p>
    </div>
  );
}
