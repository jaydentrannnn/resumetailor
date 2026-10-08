import { useState } from "react";
import { Card, DataList } from "../../components/ui";
import { useRunState } from "../../state/runState";

/**
 * One field belongs to the profile; postings supply role-specific relevance. `embedded`
 * drops the tile for the onboarding Field step, which is already one.
 */
export function TargetFieldSection({ embedded = false }: { embedded?: boolean } = {}) {
  const { config, settings, settingsLoaded, setTargetField } = useRunState();
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function choose(value: string) {
    setSaving(true);
    setError(null);
    try {
      await setTargetField(value || null);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSaving(false);
    }
  }

  return (
    <Card
      embedded={embedded}
      className={embedded ? "border-t border-line pt-4" : ""}
      title="Target field"
      description="Saved for this profile and used for every tailoring run."
    >
      <label className="grid min-w-0 gap-3 text-sm sm:grid-cols-2 sm:items-center">
        <span className="font-medium text-ink">Which field are you targeting?</span>
        <select
          className="field"
          value={config?.target_field ?? ""}
          disabled={!settingsLoaded || !config || saving}
          onChange={(event) => void choose(event.target.value)}
        >
          <option value="">Existing guidance</option>
          {(config?.target_fields ?? []).map((field) => (
            <option key={field.id} value={field.id}>
              {field.label}
            </option>
          ))}
        </select>
      </label>
      <p className="mt-3 text-sm text-ink-muted" aria-live="polite">
        {saving ? "Saving target field…" : config?.target_field_summary}
      </p>
      <p className="mt-2 text-sm text-ink-muted">
        Each posting determines which of your experiences matter. Every field uses your source facts
        and the same length limits. Your custom writing styles are preserved.
      </p>
      <DataList
        className="mt-4"
        items={(["rewrite", "expand", "cover"] as const).map((stage) => ({
          label:
            stage === "rewrite"
              ? "Resume bullets"
              : stage === "expand"
                ? "Experience expansion"
                : "Cover letter",
          value:
            settings[`${stage}_style`] !== null
              ? "Custom style"
              : config?.target_field
                ? "Field default"
                : "Existing default",
        }))}
      />
      {error && (
        <p role="alert" className="mt-2 text-sm text-danger">
          {error}
        </p>
      )}
    </Card>
  );
}
