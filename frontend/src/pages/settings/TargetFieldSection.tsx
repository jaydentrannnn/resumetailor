import { useState } from "react";
import { Card } from "../../components/ui";
import { useRunState } from "../../state/runState";

/** One field belongs to the profile; postings supply role-specific relevance. */
export function TargetFieldSection() {
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
    <Card title="Target field" description="Saved for this profile and used for every tailoring run.">
      <label className="block space-y-2 text-sm">
        <span className="font-medium text-ink">Which field are you targeting?</span>
        <select
          className="w-full rounded-md border border-line bg-paper px-3 py-2 text-ink"
          value={config?.target_field ?? ""}
          disabled={!settingsLoaded || !config || saving}
          onChange={(event) => void choose(event.target.value)}
        >
          <option value="">Existing guidance</option>
          {(config?.target_fields ?? []).map((field) => (
            <option key={field.id} value={field.id}>{field.label}</option>
          ))}
        </select>
      </label>
      <p className="mt-3 text-sm text-ink-muted" aria-live="polite">
        {saving ? "Saving target field…" : config?.target_field_summary}
      </p>
      <p className="mt-2 text-sm text-ink-muted">
        Each posting determines which of your experiences matter. Every field uses your
        source facts and the same length limits. Your custom writing styles are preserved.
      </p>
      <dl className="mt-3 space-y-1 text-sm text-ink-muted">
        {(["rewrite", "expand", "cover"] as const).map((stage) => (
          <div key={stage} className="flex justify-between gap-3">
            <dt>{stage === "rewrite" ? "Resume bullets" : stage === "expand" ? "Experience expansion" : "Cover letter"}</dt>
            <dd>{settings[`${stage}_style`] !== null ? "Custom style" : config?.target_field ? "Field default" : "Existing default"}</dd>
          </div>
        ))}
      </dl>
      {error && <p role="alert" className="mt-2 text-sm text-danger">{error}</p>}
    </Card>
  );
}
