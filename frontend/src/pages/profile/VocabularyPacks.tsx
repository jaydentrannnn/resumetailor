import { useState } from "react";
import { describe } from "../../lib/errors";
import { useToast } from "../../lib/toast";
import { useLibraryState } from "../../state/libraryState";
import { useRunState } from "../../state/runState";

/**
 * Skill-vocabulary packs as a checklist. Packs the target field brings are always on
 * (ticked and locked, with the field named); any other pack toggles and saves at once.
 */
export function VocabularyPacks({ heading = true }: { heading?: boolean } = {}) {
  const toast = useToast();
  const { config } = useRunState();
  const { packs, enabledPacks, setEnabled } = useLibraryState();
  const [busy, setBusy] = useState(false);
  const field = config?.target_fields?.find((f) => f.id === config?.target_field);
  const fromField = new Set(field?.packs ?? []);
  // Packs every target field brings (the general programming and data tools).
  const presets = config?.target_fields ?? [];
  const everyField = (id: string) =>
    presets.length > 0 && presets.every((f) => f.packs?.includes(id));

  async function toggle(id: string, on: boolean) {
    setBusy(true);
    try {
      await setEnabled(on ? [...enabledPacks, id] : enabledPacks.filter((p) => p !== id));
    } catch (err) {
      toast.error("Could not change skill vocabulary", describe(err).detail);
    } finally {
      setBusy(false);
    }
  }

  if (!packs.length) return <p className="text-sm text-ink-muted">Loading vocabulary packs…</p>;
  return (
    <fieldset disabled={busy}>
      <legend className={heading ? "text-sm font-semibold text-ink" : "sr-only"}>
        Skill vocabulary
      </legend>
      <p className="mt-1 text-sm text-ink-muted">
        Teaches ResumeTailor that different spellings mean the same skill (for example “MS Excel”
        and “Excel”).
      </p>
      <ul className="mt-2 grid gap-2 sm:grid-cols-2">
        {packs.map((pack) => {
          const locked = fromField.has(pack.id);
          return (
            <li key={pack.id}>
              <label className="flex items-start gap-2 text-sm">
                <input
                  type="checkbox"
                  className="mt-1"
                  checked={locked || enabledPacks.includes(pack.id)}
                  disabled={locked}
                  onChange={(e) => void toggle(pack.id, e.target.checked)}
                />
                <span>
                  <span className="font-medium text-ink">{pack.label}</span>
                  <span className="block text-xs text-ink-muted">
                    {!locked
                      ? pack.description
                      : everyField(pack.id)
                        ? `Included with every field. ${pack.description}`
                        : `Included with ${field?.label}`}
                  </span>
                </span>
              </label>
            </li>
          );
        })}
      </ul>
    </fieldset>
  );
}
