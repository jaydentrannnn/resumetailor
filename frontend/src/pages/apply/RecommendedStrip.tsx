import type { SourceField } from "../../api";
import { Button, Tile } from "../../components/ui";
import { FIELD_LABELS, SOURCE_FIELDS, recommendedEntries } from "../../lib/sources";
/** Catalog lists tagged with the user's fields that they do not have yet, one click each. */
export function RecommendedStrip({
  fields,
  recommended,
  picking,
  onPicking,
  onFieldsChange,
  onAdd,
  onDismiss,
}: {
  fields: SourceField[];
  recommended: ReturnType<typeof recommendedEntries>;
  picking: boolean;
  onPicking: (on: boolean) => void;
  onFieldsChange: (fields: SourceField[]) => void;
  onAdd: (entry: ReturnType<typeof recommendedEntries>[number]) => void;
  onDismiss: () => void;
}) {
  return (
    <Tile
      aria-label="Recommended for your fields"
      title="Recommended for your fields"
      meta={fields.length ? fields.map((field) => FIELD_LABELS[field]).join(" · ") : undefined}
      actions={
        <>
          {fields.length > 0 && !picking && (
            <Button size="sm" variant="ghost" onClick={() => onPicking(true)}>
              Change fields
            </Button>
          )}
          <Button
            size="sm"
            variant="ghost"
            aria-label="Dismiss recommendations"
            onClick={onDismiss}
          >
            ×
          </Button>
        </>
      }
      className="space-y-3 text-sm"
    >
      {(fields.length === 0 || picking) && (
        <div className="space-y-2">
          <p className="text-xs text-ink-muted">
            {fields.length === 0
              ? "Pick the kinds of jobs you want and we will suggest job lists for them."
              : "Suggestions follow these fields."}
          </p>
          <div role="group" aria-label="Your fields" className="flex flex-wrap gap-1.5">
            {SOURCE_FIELDS.map((field) => {
              const on = fields.includes(field);
              return (
                <button
                  key={field}
                  type="button"
                  aria-pressed={on}
                  className={`rounded-sm border px-2.5 py-0.5 text-xs ${on ? "border-selected-line bg-selected text-on-selected" : "border-line text-ink-muted hover:border-accent"}`}
                  onClick={() =>
                    onFieldsChange(on ? fields.filter((f) => f !== field) : [...fields, field])
                  }
                >
                  {FIELD_LABELS[field]}
                </button>
              );
            })}
          </div>
          {picking && (
            <Button size="sm" variant="secondary" onClick={() => onPicking(false)}>
              Done
            </Button>
          )}
        </div>
      )}
      {fields.length > 0 && recommended.length > 0 && (
        <ul className="flex flex-wrap gap-2">
          {recommended.map((entry) => (
            <li key={entry.id}>
              <Button
                size="sm"
                variant="secondary"
                title={entry.description}
                aria-label={`Add ${entry.name}`}
                onClick={() => onAdd(entry)}
              >
                + {entry.name}
              </Button>
            </li>
          ))}
        </ul>
      )}
    </Tile>
  );
}
