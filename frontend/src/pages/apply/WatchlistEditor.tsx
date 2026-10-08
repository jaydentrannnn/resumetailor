import { useState } from "react";
import { fetchWatchlists, resolveBoard, type BoardConfig, type SourceConfig } from "../../api";
import { Button } from "../../components/ui";
import { describe } from "../../lib/errors";
import { addBoard, ATS_LABELS, hasBoard, removeBoard } from "../../lib/watchlist";
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
              className="flex min-w-0 items-center gap-1 rounded-sm bg-sunken px-2 py-0.5 text-xs [overflow-wrap:anywhere]"
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
        <Button variant="secondary" size="sm" type="submit" disabled={adding || !link.trim()}>
          {adding ? "Checking…" : "Add company"}
        </Button>
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
                  <Button
                    size="sm"
                    variant="secondary"
                    key={key}
                    type="button"
                    disabled={added || adding}
                    title={failed[key] ?? (added ? "Already on your watchlist" : "Check and add")}
                    className={`${
                      failed[key] ? "border-danger/40 text-danger line-through" : "border-line"
                    }`}
                    onClick={() => void add({ ...board }, key)}
                  >
                    {added ? "✓ " : "+ "}
                    {board.company}
                  </Button>
                );
              })}
            </div>
          </div>
        ))
      )}
    </div>
  );
}
