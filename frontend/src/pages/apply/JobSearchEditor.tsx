import type { SourceConfig } from "../../api";
import {
  joinPhrases,
  MAX_PHRASES,
  PROVIDER_LABELS,
  providerOf,
  splitPhrases,
  type SearchProvider,
} from "../../lib/sources";
import { ChipInput } from "./ChipInput";
/**
 * Search phrases (at most five). Each phrase is one search; the list is stored
 * comma-joined in `SourceConfig.query`.
 */
export function PhraseChips({
  query,
  onChange,
}: {
  query: string;
  onChange: (query: string) => void;
}) {
  const phrases = splitPhrases(query);
  return (
    <div>
      <ChipInput
        label="Search phrases"
        noun="phrase"
        chips={phrases}
        max={MAX_PHRASES}
        placeholder="e.g. financial analyst"
        hint={`Each phrase is searched on its own (${phrases.length}/${MAX_PHRASES}).`}
        onChange={(next) => onChange(joinPhrases(next))}
      />
      {phrases.length === 0 && (
        <p className="mt-1 text-xs text-attn">
          Add at least one phrase; an empty search can&apos;t be saved.
        </p>
      )}
    </div>
  );
}

/**
 * A keyword job-search source (`job_search` source): queries Adzuna or USAJobs by
 * phrase (each searched separately), location, and recency. The provider is fixed by
 * where the search was created; its API keys are entered once in the Connect dialog, so
 * this editor only points there (`onConnect`) when they are missing.
 */
export function JobSearchEditor({
  source,
  onChange,
  connected = true,
  onConnect,
  onProvider,
}: {
  source: SourceConfig;
  onChange: (next: SourceConfig) => void;
  /** False when the provider's keys are not saved yet; null while that is being checked. */
  connected?: boolean | null;
  onConnect?: () => void;
  /** Given for a search that is not saved yet: the engine can still be chosen. */
  onProvider?: (provider: SearchProvider) => void;
}) {
  const provider = providerOf(source);
  const label = PROVIDER_LABELS[provider];

  return (
    <div className="space-y-3">
      {onProvider ? (
        <label className="block text-xs">
          <span className="font-medium">Search engine</span>
          <select
            aria-label="Search engine"
            className="field mt-1 w-full text-sm"
            value={provider}
            onChange={(e) => onProvider(e.target.value as SearchProvider)}
          >
            {(Object.keys(PROVIDER_LABELS) as SearchProvider[]).map((key) => (
              <option key={key} value={key}>
                {PROVIDER_LABELS[key]}
              </option>
            ))}
          </select>
        </label>
      ) : (
        <p className="text-xs">
          <span className="font-medium">Search engine:</span> {label}
        </p>
      )}
      {connected === false && (
        <p role="alert" className="rounded-md bg-attn-soft p-2.5 text-xs text-attn">
          Connect {label} first: searches return nothing until its keys are saved.{" "}
          {onConnect && (
            <button type="button" className="font-medium text-accent underline" onClick={onConnect}>
              Connect {label}
            </button>
          )}
        </p>
      )}

      <PhraseChips
        query={source.query ?? ""}
        onChange={(query) => onChange({ ...source, query })}
      />

      <label className="block text-xs">
        <span className="font-medium">Search near</span>
        <input
          aria-label="Search location"
          className="field mt-1 w-full text-sm"
          placeholder="e.g. Chicago, IL (leave empty for anywhere)"
          value={source.location ?? ""}
          onChange={(e) => onChange({ ...source, location: e.target.value })}
        />
        <span className="text-ink-muted">
          Sent to {label}; the location filter below narrows further.
        </span>
      </label>
      {provider === "adzuna" && (
        <label className="block text-xs">
          <span className="font-medium">Country</span>
          <select
            aria-label="Adzuna country code"
            className="field mt-1 w-full text-sm"
            value={source.country || "us"}
            onChange={(e) => onChange({ ...source, country: e.target.value })}
          >
            {adzunaCountries(source.country).map(([code, name]) => (
              <option key={code} value={code}>
                {name}
              </option>
            ))}
          </select>
        </label>
      )}
    </div>
  );
}

/** Countries Adzuna serves (code, name); a saved code outside the list stays selectable. */
const ADZUNA_COUNTRIES: [string, string][] = [
  ["us", "United States"],
  ["gb", "United Kingdom"],
  ["ca", "Canada"],
  ["au", "Australia"],
  ["at", "Austria"],
  ["be", "Belgium"],
  ["br", "Brazil"],
  ["ch", "Switzerland"],
  ["de", "Germany"],
  ["es", "Spain"],
  ["fr", "France"],
  ["in", "India"],
  ["it", "Italy"],
  ["mx", "Mexico"],
  ["nl", "Netherlands"],
  ["nz", "New Zealand"],
  ["pl", "Poland"],
  ["sg", "Singapore"],
  ["za", "South Africa"],
];

function adzunaCountries(current: string | undefined): [string, string][] {
  const code = (current || "us").toLowerCase();
  return ADZUNA_COUNTRIES.some(([c]) => c === code)
    ? ADZUNA_COUNTRIES
    : [[code, code.toUpperCase()], ...ADZUNA_COUNTRIES];
}
