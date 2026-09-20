import { useId, useState } from "react";
import { uniqueTags } from "../lib/resumeEdit";

type ChipListFieldProps = {
  /** Visible field label. Omit when the parent renders its own header (e.g. a verb-family
   * card, where the family-name input is the header) — pass `ariaLabel` instead so the
   * input still has an accessible name. */
  label?: string;
  /** Accessible name for the text input, used only when `label` is omitted. */
  ariaLabel?: string;
  items: string[];
  onChange: (items: string[]) => void;
  /** Optional datalist suggestions (e.g. the stored tag vocabulary). */
  suggestions?: string[];
  /** Called when the user commits a token that was not already in `items`. Receives the
   * normalized token (after `normalize`, if given), matching what's actually stored. */
  onAddNew?: (token: string) => void;
  placeholder?: string;
  /** Applied to every committed token before validation, dedupe, and storage — and to
   * `items` on render, so a chip always reads exactly as it will be saved (e.g. verbs
   * lowercased). Note this means removing one chip can also rewrite the casing of the
   * others, since render always re-normalizes the full list. */
  normalize?: (token: string) => string;
  /** Error message for a token that must be rejected, or null to accept it. Receives the
   * *normalized* token. A rejected token is not added; it's kept in the draft so the user
   * can fix it rather than retype it. This is a gate, not the source of truth — data that
   * arrives already-invalid (e.g. loaded from the server) is still displayed. */
  validate?: (token: string) => string | null;
  /** Token separators, as a regex passed to `String.split`. Default splits only on
   * commas. Verbs pass `/[,\s]+/` so a paste with newlines (which browsers flatten to
   * spaces in a single-line input) still splits into separate tokens. */
  separators?: RegExp;
};

/**
 * Removable tiles for a string list, with a text input that commits on
 * Enter, comma, or blur. Items are treated as a case-insensitive set —
 * duplicates (including differing only by case) never appear twice.
 */
export function ChipListField({
  label,
  ariaLabel,
  items,
  onChange,
  suggestions,
  onAddNew,
  placeholder = "Type and press Enter",
  normalize,
  validate,
  separators = /,/,
}: ChipListFieldProps) {
  const [draft, setDraft] = useState("");
  const [error, setError] = useState<string | null>(null);
  const listId = useId();
  const labelId = useId();
  const errorId = useId();
  // Always render/operate on the unique, normalized set so a stale or server-loaded
  // parent list can't show dupes or a casing that would change the moment it's re-saved.
  const uniqueItems = uniqueTags(normalize ? items.map(normalize) : items);

  function commit(raw: string) {
    const tokens = raw
      .split(separators)
      .map((t) => t.trim())
      .filter(Boolean);
    if (!tokens.length) {
      setDraft("");
      setError(null);
      return;
    }

    const have = new Set(uniqueItems.map((t) => t.toLowerCase()));
    const next = [...uniqueItems];
    const rejected: string[] = [];
    let firstError: string | null = null;

    for (const token of tokens) {
      const t = normalize ? normalize(token) : token;
      if (!t) continue;
      const err = validate?.(t) ?? null;
      if (err) {
        rejected.push(token);
        firstError ??= err;
        continue;
      }
      if (have.has(t.toLowerCase())) continue;
      have.add(t.toLowerCase());
      next.push(t);
      onAddNew?.(t);
    }

    setError(firstError);
    // Keep rejected text in the draft so the user can fix it instead of retyping.
    setDraft(rejected.join(", "));
    if (next.length !== uniqueItems.length) onChange(uniqueTags(next));
  }

  function removeAt(index: number) {
    onChange(uniqueItems.filter((_, i) => i !== index));
  }

  return (
    <div className="block text-sm">
      {label && (
        <span id={labelId} className="mb-1 block text-ink-muted">
          {label}
        </span>
      )}
      <div className="flex min-h-[2.25rem] flex-wrap items-center gap-1.5 rounded-md border border-line bg-paper/40 px-2 py-1.5 focus-within:border-accent">
        {/* Neutral by default — a committed token, not a selection state. At the
            volumes this renders (a resume's full tag vocabulary, every bullet's
            own tags) an accent-filled pill per item turned the accent colour into
            page texture instead of a signal. Accent is reserved for the button
            it takes on hover — the one moment a chip is "active". */}
        {uniqueItems.map((item, i) => (
          <span
            key={item.toLowerCase()}
            className="inline-flex items-center gap-1 rounded-full border border-line bg-paper px-2 py-0.5 text-xs font-medium text-ink"
          >
            {item}
            <button
              type="button"
              title={`Remove ${item}`}
              aria-label={`Remove ${item}`}
              onClick={() => removeAt(i)}
              className="flex min-h-6 min-w-6 items-center justify-center rounded-full text-ink-muted hover:bg-accent hover:text-on-accent"
            >
              ×
            </button>
          </span>
        ))}
        <input
          type="text"
          value={draft}
          list={suggestions?.length ? listId : undefined}
          placeholder={uniqueItems.length ? "" : placeholder}
          aria-labelledby={label ? labelId : undefined}
          aria-label={label ? undefined : ariaLabel}
          aria-invalid={error ? true : undefined}
          aria-describedby={error ? errorId : undefined}
          onChange={(e) => {
            const v = e.target.value;
            // Commit as soon as a separator is typed. `.split` rather than `.test` so a
            // global-flagged `separators` regex can't leak stateful `lastIndex` bugs here.
            if (v.split(separators).length > 1) {
              commit(v);
              return;
            }
            setDraft(v);
          }}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              e.preventDefault();
              commit(draft);
            } else if (e.key === "Backspace" && !draft && uniqueItems.length) {
              removeAt(uniqueItems.length - 1);
            }
          }}
          onBlur={() => {
            if (draft.trim()) commit(draft);
          }}
          className="min-w-[8rem] flex-1 border-0 bg-transparent py-0.5 text-sm"
        />
      </div>
      {error && (
        <p id={errorId} className="mt-1 text-xs text-danger">
          {error}
        </p>
      )}
      {suggestions && suggestions.length > 0 && (
        <datalist id={listId}>
          {suggestions.map((s) => (
            <option key={s} value={s} />
          ))}
        </datalist>
      )}
    </div>
  );
}
