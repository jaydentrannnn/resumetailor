import type { SourceConfig } from "../../api";
import { ChipInput } from "./ChipInput";
/**
 * The filters every source has, the same for a job list, a search and a watchlist:
 * titles to keep, titles to skip, places, and how old a posting may be.
 */
export function FiltersEditor({
  source,
  onChange,
  defaultDays,
}: {
  source: SourceConfig;
  onChange: (next: SourceConfig) => void;
  /** The limit when the box is empty: a number for searches and watchlists; null for a list (Apply settings' limit). */
  defaultDays: number | null;
}) {
  return (
    <fieldset className="space-y-4 border-t border-line pt-4">
      <legend className="text-sm font-semibold">Filters</legend>
      <ChipInput
        label="Keep titles containing"
        noun="keyword"
        chips={source.include ?? []}
        placeholder="e.g. analyst (empty keeps every title)"
        onChange={(include) => onChange({ ...source, include })}
      />
      <ChipInput
        label="Skip titles containing"
        noun="skipped word"
        chips={source.exclude ?? []}
        placeholder="e.g. senior"
        onChange={(exclude) => onChange({ ...source, exclude })}
      />
      <ChipInput
        label="Only these locations"
        noun="location"
        chips={source.locations ?? []}
        placeholder="e.g. New York, Remote (empty means anywhere)"
        onChange={(locations) => onChange({ ...source, locations })}
      />
      <label className="block text-xs">
        <span className="font-medium">Only postings from the last</span>
        <input
          aria-label="Days old limit"
          className="field mx-1 inline-block w-16"
          type="number"
          min={0}
          max={365}
          placeholder={defaultDays === null ? "any" : String(defaultDays)}
          value={source.max_age_days ?? ""}
          onChange={(e) =>
            onChange({
              ...source,
              max_age_days:
                e.target.value === ""
                  ? defaultDays
                  : Math.min(365, Math.max(0, Number(e.target.value) || 0)),
            })
          }
        />
        days
        {defaultDays === null && (
          <span className="block text-ink-muted">
            Empty follows the Apply settings limit; a longer limit here widens it for this list.
          </span>
        )}
      </label>
    </fieldset>
  );
}
