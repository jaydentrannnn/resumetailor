import type { SourceConfig } from "../../api";
import { NO_FILTERS } from "../../lib/globalFilters";
import { ChipInput } from "./ChipInput";
import { useEverySource } from "./everySource";
/**
 * The filters every source has, the same for a job list, a search and a watchlist:
 * titles to keep, titles to skip, places, and how old a posting may be. The filters for
 * every source show as locked chips; this source's own words are added to them.
 */
export function FiltersEditor({
  source,
  onChange,
  defaultDays,
  canChangeGlobal = false,
}: {
  source: SourceConfig;
  onChange: (next: SourceConfig) => void;
  /** The limit when the box is empty: a number for searches and watchlists; null for a list (the every-source limit). */
  defaultDays: number | null;
  /** Offer "Change them there" (a saved source; a new one would lose its draft). */
  canChangeGlobal?: boolean;
}) {
  const every = useEverySource();
  const global = every?.filters ?? NO_FILTERS;
  const ignoreInclude = !!source.ignore_global_include;
  return (
    <fieldset className="space-y-4 border-t border-line pt-4">
      <legend className="text-sm font-semibold">Filters</legend>
      {every && (
        <p className="text-xs text-ink-muted">
          Green chips come from Filters for every source and apply here too.{" "}
          {canChangeGlobal && (
            <button type="button" className="rt-link font-medium" onClick={every.openGlobal}>
              Change them there
            </button>
          )}
        </p>
      )}
      <div className="space-y-1.5">
        <ChipInput
          label="Keep titles containing"
          noun="keyword"
          chips={source.include ?? []}
          locked={global.include}
          lockedOff={ignoreInclude}
          placeholder="e.g. analyst (empty keeps every title)"
          onChange={(include) => onChange({ ...source, include })}
        />
        {global.include.length > 0 && (
          <label className="flex items-center gap-2 text-xs text-ink-muted">
            <input
              type="checkbox"
              className="accent-[var(--color-accent)]"
              checked={ignoreInclude}
              onChange={(e) => onChange({ ...source, ignore_global_include: e.target.checked })}
            />
            Don't use the global keep words for this source
          </label>
        )}
      </div>
      <ChipInput
        label="Skip titles containing"
        noun="skipped word"
        chips={source.exclude ?? []}
        locked={global.exclude}
        placeholder="e.g. senior"
        onChange={(exclude) => onChange({ ...source, exclude })}
      />
      <ChipInput
        label="Only these locations"
        noun="location"
        chips={source.locations ?? []}
        locked={global.locations}
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
        <span className="block text-ink-muted">
          {defaultDays === null
            ? "Empty follows Filters for every source; a longer limit here widens it for this list."
            : "The longer of this and the limit in Filters for every source wins."}
        </span>
      </label>
      {every && (
        <p className="text-xs">
          <span className="font-medium">Eligibility</span>
          <span className="block text-ink-muted">{every.eligibility}. Same for every source.</span>
        </p>
      )}
    </fieldset>
  );
}
