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
} from "../../lib/sources";
import { addBoard, ATS_LABELS, hasBoard, parseWords, removeBoard } from "../../lib/watchlist";

/**
 * Search phrases as removable chips (at most five). Each phrase is one search; the list is
 * stored comma-joined in `SourceConfig.query`. Enter or a comma adds the typed phrase.
 */
export function PhraseChips({
  query,
  onChange,
}: {
  query: string;
  onChange: (query: string) => void;
}) {
  const inputId = useId();
  const hintId = useId();
  const phrases = splitPhrases(query);
  const [text, setText] = useState("");
  const full = phrases.length >= MAX_PHRASES;

  function add() {
    const next = joinPhrases([...phrases, ...text.split(",")]);
    if (next !== query) onChange(next);
    setText("");
  }

  return (
    <div className="text-xs">
      <label htmlFor={inputId} className="font-medium">
        Search phrases
      </label>
      {phrases.length > 0 && (
        <ul aria-label="Search phrases" className="mt-1 flex flex-wrap gap-1.5">
          {phrases.map((phrase) => (
            <li
              key={phrase}
              className="flex items-center gap-1 rounded-full border border-line bg-paper px-2 py-0.5"
            >
              {phrase}
              <button
                type="button"
                aria-label={`Remove phrase ${phrase}`}
                className="ml-0.5 text-ink-muted hover:text-danger"
                onClick={() => onChange(joinPhrases(phrases.filter((p) => p !== phrase)))}
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
          aria-describedby={hintId}
          className="field min-w-0 flex-1 text-sm"
          placeholder={full ? "Five phrases is the most" : "e.g. financial analyst"}
          disabled={full}
          value={text}
          onChange={(e) => {
            const value = e.target.value;
            if (value.includes(",")) {
              const parts = value.split(",");
              const rest = parts.pop() ?? "";
              const next = joinPhrases([...phrases, ...parts]);
              if (next !== query) onChange(next);
              setText(rest);
            } else setText(value);
          }}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              e.preventDefault();
              if (text.trim()) add();
            } else if (e.key === "Backspace" && !text && phrases.length) {
              onChange(joinPhrases(phrases.slice(0, -1)));
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
      <p id={hintId} className="mt-1 text-ink-muted">
        Each phrase is searched on its own ({phrases.length}/{MAX_PHRASES}).
      </p>
      {phrases.length === 0 && (
        <p className="mt-1 text-warn">Add at least one phrase; an empty search can't be saved.</p>
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

function WordsField({
  label,
  hint,
  words,
  onChange,
}: {
  label: string;
  hint: string;
  words: string[];
  onChange: (words: string[]) => void;
}) {
  const [text, setText] = useState(words.join(", "));
  return (
    <label className="block text-xs">
      <span className="font-medium">{label}</span>
      <input
        className="field mt-1 text-sm"
        value={text}
        onChange={(e) => setText(e.target.value)}
        onBlur={() => {
          const next = parseWords(text);
          setText(next.join(", "));
          onChange(next);
        }}
      />
      <span className="text-ink-muted">{hint}</span>
    </label>
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
    <div className="mt-2 space-y-3 rounded-md border border-line p-3">
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
      <WordsField
        label="Titles must contain one of"
        hint="Comma-separated. Leave empty to keep every title."
        words={source.include ?? []}
        onChange={(include) => onChange({ ...source, include })}
      />
      <WordsField
        label="Skip titles containing"
        hint="Comma-separated."
        words={source.exclude ?? []}
        onChange={(exclude) => onChange({ ...source, exclude })}
      />
      <WordsField
        label="Locations"
        hint='Comma-separated, e.g. "NY, Chicago, Remote". Leave empty for anywhere.'
        words={source.locations ?? []}
        onChange={(locations) => onChange({ ...source, locations })}
      />
      <label className="block text-xs">
        Postings updated in the last{" "}
        <input
          className="field mx-1 inline-block w-16"
          type="number"
          min={0}
          max={365}
          value={source.max_age_days ?? 7}
          onChange={(e) =>
            onChange({
              ...source,
              max_age_days: Math.min(365, Math.max(0, Number(e.target.value) || 0)),
            })
          }
        />{" "}
        days
      </label>
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
}: {
  source: SourceConfig;
  onChange: (next: SourceConfig) => void;
  /** False when the provider's keys are not saved yet; null while that is being checked. */
  connected?: boolean | null;
  onConnect?: () => void;
}) {
  const provider = providerOf(source);
  const label = PROVIDER_LABELS[provider];

  return (
    <div className="mt-2 space-y-3 rounded-md border border-line p-3">
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

      <p className="text-xs">
        <span className="font-medium">Search engine:</span> {label}
      </p>
      {provider === "adzuna" && (
        <label className="block text-xs">
          <span className="font-medium">Country code</span>
          <input
            aria-label="Adzuna country code"
            className="field mt-1 w-full text-sm"
            placeholder="us"
            value={source.country ?? "us"}
            onChange={(e) => onChange({ ...source, country: e.target.value.toLowerCase().trim() })}
          />
        </label>
      )}

      <PhraseChips
        query={source.query ?? ""}
        onChange={(query) => onChange({ ...source, query })}
      />

      <label className="block text-xs">
        <span className="font-medium">Location</span>
        <input
          aria-label="Search location"
          className="field mt-1 text-sm w-full"
          placeholder="e.g. Chicago, IL (leave empty for anywhere)"
          value={source.location ?? ""}
          onChange={(e) => onChange({ ...source, location: e.target.value })}
        />
      </label>

      <WordsField
        label="Titles must contain one of"
        hint="Comma-separated. Leave empty to keep every title."
        words={source.include ?? []}
        onChange={(include) => onChange({ ...source, include })}
      />
      <WordsField
        label="Skip titles containing"
        hint="Comma-separated."
        words={source.exclude ?? []}
        onChange={(exclude) => onChange({ ...source, exclude })}
      />
      <WordsField
        label="Locations"
        hint='Comma-separated, e.g. "NY, Chicago, Remote". Leave empty for anywhere.'
        words={source.locations ?? []}
        onChange={(locations) => onChange({ ...source, locations })}
      />
      <label className="block text-xs">
        Postings updated in the last{" "}
        <input
          aria-label="Days old limit"
          className="field mx-1 inline-block w-16"
          type="number"
          min={0}
          max={365}
          value={source.max_age_days ?? 14}
          onChange={(e) =>
            onChange({
              ...source,
              max_age_days: Math.min(365, Math.max(0, Number(e.target.value) || 0)),
            })
          }
        />{" "}
        days
      </label>
    </div>
  );
}
