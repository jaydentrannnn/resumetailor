import { useState } from "react";
import {
  fetchSourceSections,
  fetchWatchlists,
  resolveBoard,
  type BoardConfig,
  type SourceConfig,
} from "../../api";
import { describe } from "../../lib/errors";
import { addBoard, ATS_LABELS, hasBoard, parseWords, removeBoard } from "../../lib/watchlist";

/**
 * The categories a README source offers, as checkboxes. The headings are read from the
 * README on demand, so a renamed category shows up instead of silently matching nothing.
 */
export function CategoryPicker({
  source,
  onChange,
}: {
  source: SourceConfig;
  onChange: (next: SourceConfig) => void;
}) {
  const [sections, setSections] = useState<string[] | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  async function load() {
    setLoading(true);
    setError("");
    try {
      setSections(await fetchSourceSections(source.url));
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
