import { useEffect, useState } from "react";
import {
  buildSearchPreset,
  fetchSearchPresets,
  type SearchPresetBuild,
  type SearchPresetChoices,
} from "../../api";
import { Button } from "../../components/ui";
import { FilterChips } from "./FilterChips";

/**
 * "Start from a preset": pick a level and an industry (or positions) and fill the search
 * phrases and title filters in one step. Everything it fills stays editable below; the
 * phrase rules live on the server so the SPA never copies them.
 */
export function SearchPresetPicker({ onApply }: { onApply: (preset: SearchPresetBuild) => void }) {
  const [choices, setChoices] = useState<SearchPresetChoices | null>(null);
  const [loadFailed, setLoadFailed] = useState(false);
  const [error, setError] = useState("");
  const [level, setLevel] = useState("intern");
  const [positions, setPositions] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let live = true;
    fetchSearchPresets()
      .then((next) => live && setChoices(next))
      .catch(() => live && setLoadFailed(true));
    return () => {
      live = false;
    };
  }, []);

  if (loadFailed) return <p className="text-xs text-ink-muted">Presets are unavailable right now.</p>;
  if (!choices) return null;

  const labels = Object.fromEntries(choices.positions.map((p) => [p.id, p.label]));
  async function apply() {
    setBusy(true);
    setError("");
    try {
      onApply(await buildSearchPreset(positions, level));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <fieldset className="space-y-2 rounded-md border border-line p-3">
      <legend className="px-1 text-xs font-medium">Start from a preset</legend>
      <div className="grid grid-cols-2 gap-2">
        <label className="block text-xs">
          <span className="font-medium">Level</span>
          <select
            aria-label="Preset level"
            className="field mt-1 w-full text-sm"
            value={level}
            onChange={(e) => setLevel(e.target.value)}
          >
            {choices.levels.map((l) => (
              <option key={l.id} value={l.id}>
                {l.label}
              </option>
            ))}
          </select>
        </label>
        <label className="block text-xs">
          <span className="font-medium">Industry</span>
          <select
            aria-label="Preset industry"
            className="field mt-1 w-full text-sm"
            value=""
            onChange={(e) =>
              setPositions(choices.industries.find((i) => i.id === e.target.value)?.positions ?? [])
            }
          >
            <option value="">Choose to fill positions…</option>
            {choices.industries.map((i) => (
              <option key={i.id} value={i.id}>
                {i.label}
              </option>
            ))}
          </select>
        </label>
      </div>
      <FilterChips
        label="Preset positions"
        options={choices.positions.map((p) => p.id)}
        labels={labels}
        selected={positions}
        onChange={setPositions}
      />
      <Button size="sm" disabled={positions.length === 0 || busy} onClick={apply}>
        Fill search
      </Button>
      {error && (
        <p role="alert" className="text-xs text-danger">
          {error}
        </p>
      )}
    </fieldset>
  );
}
