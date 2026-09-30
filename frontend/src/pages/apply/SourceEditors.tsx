import { useId, useState } from "react";
import {
  fetchSourceSections,
  fetchWatchlists,
  inspectSource,
  resolveBoard,
  type BoardConfig,
  type SourceConfig,
} from "../../api";
import { describe } from "../../lib/errors";
import {
  joinPhrases,
  MAX_PHRASES,
  PROVIDER_LABELS,
  providerOf,
  splitPhrases,
  type SearchProvider,
} from "../../lib/sources";
import { addBoard, ATS_LABELS, hasBoard, removeBoard } from "../../lib/watchlist";

/** Trim, drop blanks and case-insensitive repeats; keeps the first spelling. */
function cleanChips(items: string[], max = Infinity): string[] {
  const seen = new Set<string>();
  const out: string[] = [];
  for (const item of items) {
    const text = item.trim();
    const key = text.toLowerCase();
    if (!text || seen.has(key)) continue;
    seen.add(key);
    out.push(text);
    if (out.length >= max) break;
  }
  return out;
}

/**
 * The one list input every source editor uses: removable chips plus a box. Enter, a
 * comma or leaving the box adds what was typed (pasting "a, b, c" adds three);
 * Backspace on an empty box removes the last chip.
 */
export function ChipInput({
  label,
  chips,
  onChange,
  noun,
  placeholder,
  hint,
  max,
}: {
  label: string;
  chips: string[];
  onChange: (chips: string[]) => void;
  /** Singular name used in each chip's "Remove <noun> <chip>" button. */
  noun: string;
  placeholder?: string;
  hint?: string;
  /** The most chips allowed; the box is disabled once reached. */
  max?: number;
}) {
  const inputId = useId();
  const hintId = useId();
  const [text, setText] = useState("");
  const full = max !== undefined && chips.length >= max;

  const commit = (extra: string[]) => {
    const next = cleanChips([...chips, ...extra], max);
    if (next.length !== chips.length) onChange(next);
  };
  const add = () => {
    commit(text.split(","));
    setText("");
  };

  return (
    <div className="text-xs">
      <label htmlFor={inputId} className="font-medium">
        {label}
      </label>
      {chips.length > 0 && (
        <ul aria-label={label} className="mt-1 flex flex-wrap gap-1.5">
          {chips.map((chip) => (
            <li
              key={chip}
              className="flex items-center gap-1 rounded-full border border-line bg-paper px-2 py-0.5"
            >
              {chip}
              <button
                type="button"
                aria-label={`Remove ${noun} ${chip}`}
                className="ml-0.5 text-ink-muted hover:text-danger"
                onClick={() => onChange(chips.filter((c) => c !== chip))}
              >
                ×
              </button>
            </li>
          ))}
        </ul>
      )}
      <div className="mt-1 flex gap-2">
        <input
          id={inputId}
          aria-describedby={hint ? hintId : undefined}
          className="field min-w-0 flex-1 text-sm"
          placeholder={full ? `${max} is the most` : placeholder}
          disabled={full}
          value={text}
          onChange={(e) => {
            const value = e.target.value;
            if (value.includes(",")) {
              const parts = value.split(",");
              const rest = parts.pop() ?? "";
              commit(parts);
              setText(rest);
            } else setText(value);
          }}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              e.preventDefault();
              if (text.trim()) add();
            } else if (e.key === "Backspace" && !text && chips.length) {
              onChange(chips.slice(0, -1));
            }
          }}
          onBlur={() => {
            if (text.trim()) add();
          }}
        />
        <button
          type="button"
          className="rounded-md border border-line px-3 py-1 text-xs font-medium disabled:opacity-50"
          disabled={full || !text.trim()}
          onClick={add}
        >
          Add
        </button>
      </div>
      {hint && (
        <p id={hintId} className="mt-1 text-ink-muted">
          {hint}
        </p>
      )}
    </div>
  );
}

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
        <p className="mt-1 text-xs text-warn">
          Add at least one phrase; an empty search can&apos;t be saved.
        </p>
      )}
    </div>
  );
}

/**
 * The categories a README source offers, as checkboxes. The headings are read from the
 * README on demand, so a renamed category shows up instead of silently matching nothing.
 */
export function CategoryPicker({
  source,
  onChange,
  initialSections = null,
}: {
  source: SourceConfig;
  onChange: (next: SourceConfig) => void;
  /** Headings already read (the Add source dialog's inspect step); skips the fetch. */
  initialSections?: string[] | null;
}) {
  const [sections, setSections] = useState<string[] | null>(initialSections);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  async function load() {
    setLoading(true);
    setError("");
    try {
      // The inspect endpoint knows every README format, including per-company link tables.
      setSections(
        source.kind === "company_link_table"
          ? (await inspectSource(source.url)).sections
          : await fetchSourceSections(source.url),
      );
    } catch (reason) {
      setError(describe(reason).detail);
    } finally {
      setLoading(false);
    }
  }

  if (sections === null) {
    return (
      <div className="mt-1">
        <button
          type="button"
          className="text-xs text-accent underline disabled:opacity-50"
          onClick={load}
          disabled={loading}
        >
          {loading ? "Reading categories…" : "Choose categories"}
        </button>
        {error && (
          <p role="alert" className="text-xs text-danger">
            {error}
          </p>
        )}
      </div>
    );
  }
  const chosen = new Set(source.categories);
  const missing = source.categories.filter((c) => !sections.includes(c));
  return (
    <fieldset className="mt-2 space-y-1">
      <legend className="text-xs font-medium">Categories</legend>
      {sections.length === 0 && (
        <p className="text-xs text-ink-muted">
          This list has no category headings; every posting on it is searched.
        </p>
      )}
      {sections.map((name) => (
        <label key={name} className="flex items-center gap-2 text-xs">
          <input
            type="checkbox"
            checked={chosen.has(name)}
            onChange={(e) =>
              onChange({
                ...source,
                categories: e.target.checked
                  ? [...source.categories, name]
                  : source.categories.filter((c) => c !== name),
              })
            }
          />
          {name}
        </label>
      ))}
      {missing.length > 0 && (
        <p className="text-xs text-warn">
          Not in the list any more (finds nothing): {missing.join(" · ")}
        </p>
      )}
    </fieldset>
  );
}

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
    <fieldset className="space-y-3 rounded-md border border-line p-3">
      <legend className="px-1 text-xs font-medium">Filters</legend>
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

/**
 * A company watchlist (`ats_board` source): the boards to read nightly and which of
 * their postings to keep. Every board is checked live before it is added.
 */
export function WatchlistEditor({
  source,
  onChange,
}: {
  source: SourceConfig;
  onChange: (next: SourceConfig) => void;
}) {
  const boards = source.boards ?? [];
  const [link, setLink] = useState("");
  const [adding, setAdding] = useState(false);
  const [error, setError] = useState("");
  const [suggestions, setSuggestions] = useState<Record<string, BoardConfig[]> | null>(null);
  const [failed, setFailed] = useState<Record<string, string>>({});

  const setBoards = (next: BoardConfig[]) => onChange({ ...source, boards: next });

  async function add(input: Parameters<typeof resolveBoard>[0], key?: string) {
    setAdding(true);
    setError("");
    try {
      const board = await resolveBoard(input);
      setBoards(addBoard(boards, { ats: board.ats, slug: board.slug, company: board.company }));
      if (!key) setLink("");
    } catch (reason) {
      const message = describe(reason).detail;
      if (key) setFailed((prev) => ({ ...prev, [key]: message }));
      else setError(message);
    } finally {
      setAdding(false);
    }
  }

  async function showSuggestions() {
    try {
      setSuggestions(await fetchWatchlists());
    } catch (reason) {
      setError(describe(reason).detail);
    }
  }

  return (
    <div className="space-y-3">
      <p className="text-xs font-medium">Companies</p>
      {boards.length === 0 ? (
        <p className="text-xs text-ink-muted">
          No companies yet. Paste a company's careers page, job board, or job link.
        </p>
      ) : (
        <ul className="flex flex-wrap gap-2">
          {boards.map((board) => (
            <li
              key={`${board.ats}:${board.slug}`}
              className="flex items-center gap-1 rounded-full border border-line px-2 py-0.5 text-xs"
            >
              <span>
                {board.company || board.slug}{" "}
                <span className="text-ink-muted">· {ATS_LABELS[board.ats]}</span>
              </span>
              <button
                type="button"
                aria-label={`Remove ${board.company || board.slug}`}
                className="ml-1 text-ink-muted hover:text-danger"
                onClick={() => setBoards(removeBoard(boards, board))}
              >
                ×
              </button>
            </li>
          ))}
        </ul>
      )}
      <form
        className="flex flex-wrap items-center gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          if (link.trim()) void add({ url: link.trim() });
        }}
      >
        <input
          className="field min-w-0 flex-1 text-sm"
          aria-label="Company careers page or job board link"
          placeholder="https://company.com/careers"
          value={link}
          onChange={(e) => setLink(e.target.value)}
        />
        <button
          type="submit"
          className="rounded-md border border-line px-3 py-1 text-xs font-medium disabled:opacity-50"
          disabled={adding || !link.trim()}
        >
          {adding ? "Checking…" : "Add company"}
        </button>
      </form>
      {error && (
        <p role="alert" className="text-xs text-danger">
          {error}
        </p>
      )}
      {suggestions === null ? (
        <button type="button" className="text-xs text-accent underline" onClick={showSuggestions}>
          Suggested companies
        </button>
      ) : (
        Object.entries(suggestions).map(([field, list]) => (
          <div key={field}>
            <p className="text-xs font-medium capitalize">{field}</p>
            <div className="mt-1 flex flex-wrap gap-1">
              {list.map((board) => {
                const key = `${board.ats}:${board.slug}`;
                const added = hasBoard(boards, board);
                return (
                  <button
                    key={key}
                    type="button"
                    disabled={added || adding}
                    title={failed[key] ?? (added ? "Already on your watchlist" : "Check and add")}
                    className={`rounded-full border px-2 py-0.5 text-xs disabled:opacity-50 ${
                      failed[key] ? "border-danger/40 text-danger line-through" : "border-line"
                    }`}
                    onClick={() => void add({ ...board }, key)}
                  >
                    {added ? "✓ " : "+ "}
                    {board.company}
                  </button>
                );
              })}
            </div>
          </div>
        ))
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
        <p role="alert" className="rounded-md bg-warn-soft p-2.5 text-xs text-warn">
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
