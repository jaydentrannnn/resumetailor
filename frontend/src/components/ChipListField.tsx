import { useId, useState } from "react";
import { uniqueTags } from "../lib/resumeEdit";

type ChipListFieldProps = {
  label: string;
  items: string[];
  onChange: (items: string[]) => void;
  /** Optional datalist suggestions (e.g. the stored tag vocabulary). */
  suggestions?: string[];
  /** Called when the user commits a token that was not already in `items`. */
  onAddNew?: (token: string) => void;
  placeholder?: string;
};

/**
 * Removable tiles for a string list, with a text input that commits on
 * Enter, comma, or blur. Items are treated as a case-insensitive set —
 * duplicates (including differing only by case) never appear twice.
 */
export function ChipListField({
  label,
  items,
  onChange,
  suggestions,
  onAddNew,
  placeholder = "Type and press Enter",
}: ChipListFieldProps) {
  const [draft, setDraft] = useState("");
  const listId = useId();
  // Always render/operate on the unique set so a stale parent list cannot show dupes.
  const uniqueItems = uniqueTags(items);

  function commit(raw: string) {
    /** Split on commas, merge into the set, then notify. */
    const tokens = raw
      .split(",")
      .map((t) => t.trim())
      .filter(Boolean);
    if (!tokens.length) {
      setDraft("");
      return;
    }
    const have = new Set(uniqueItems.map((t) => t.toLowerCase()));
    const next = [...uniqueItems];
    for (const token of tokens) {
      if (have.has(token.toLowerCase())) continue;
      have.add(token.toLowerCase());
      next.push(token);
      onAddNew?.(token);
    }
    onChange(uniqueTags(next));
    setDraft("");
  }

  function removeAt(index: number) {
    onChange(uniqueItems.filter((_, i) => i !== index));
  }

  return (
    <div className="block text-sm">
      <span className="mb-1 block text-ink-muted">{label}</span>
      <div className="flex min-h-[2.25rem] flex-wrap items-center gap-1.5 rounded-md border border-line bg-paper/40 px-2 py-1.5 focus-within:border-accent">
        {uniqueItems.map((item, i) => (
          <span
            key={item.toLowerCase()}
            className="inline-flex items-center gap-1 rounded-full bg-accent-soft px-2 py-0.5 text-xs font-medium text-accent"
          >
            {item}
            <button
              type="button"
              title={`Remove ${item}`}
              onClick={() => removeAt(i)}
              className="rounded-full px-0.5 text-accent/70 hover:bg-accent hover:text-white"
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
          onChange={(e) => {
            const v = e.target.value;
            // Commit each token as soon as a comma is typed.
            if (v.includes(",")) {
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
          className="min-w-[8rem] flex-1 border-0 bg-transparent py-0.5 text-sm outline-none"
        />
      </div>
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
