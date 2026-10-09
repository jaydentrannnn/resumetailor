import { useId, useState } from "react";
import { Button } from "../../components/ui";
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

/** The small globe on a chip that comes from the filters for every source. */
function GlobeMark() {
  return (
    <svg viewBox="0 0 12 12" aria-hidden="true" className="size-3 shrink-0 text-accent">
      <circle cx="6" cy="6" r="4.8" fill="none" stroke="currentColor" strokeWidth="1.2" />
      <path
        d="M1.2 6h9.6M6 1.2c1.5 1.4 2.2 3 2.2 4.8S7.5 9.4 6 10.8C4.5 9.4 3.8 7.8 3.8 6S4.5 2.6 6 1.2z"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.1"
      />
    </svg>
  );
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
  locked = [],
  lockedOff = false,
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
  /** Chips set elsewhere (the filters for every source): shown first, never removable here. */
  locked?: string[];
  /** The locked chips do not apply here; they are shown struck through. */
  lockedOff?: boolean;
}) {
  const inputId = useId();
  const hintId = useId();
  const [text, setText] = useState("");
  const full = max !== undefined && chips.length >= max;

  const lockedKeys = new Set(locked.map((c) => c.trim().toLowerCase()));
  const commit = (extra: string[]) => {
    const fresh = extra.filter((c) => !lockedKeys.has(c.trim().toLowerCase()));
    const next = cleanChips([...chips, ...fresh], max);
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
      {chips.length + locked.length > 0 && (
        <ul aria-label={label} className="mt-1 flex flex-wrap gap-1.5">
          {locked.map((chip) => (
            <li
              key={`locked-${chip}`}
              title={
                lockedOff
                  ? "Not used for this source"
                  : "From Filters for every source. Change it there."
              }
              className={`flex min-w-0 items-center gap-1 rounded-sm px-2 py-0.5 [overflow-wrap:anywhere] ${lockedOff ? "text-ink-muted line-through ring-1 ring-line-hover ring-inset" : "bg-selected-row ring-1 ring-selected-line/45 ring-inset"}`}
            >
              <GlobeMark />
              {chip}
              <span className="sr-only">
                {lockedOff ? " (every-source filter, not used here)" : " (every-source filter)"}
              </span>
            </li>
          ))}
          {chips.map((chip) => (
            <li
              key={chip}
              className="flex min-w-0 items-center gap-1 rounded-sm bg-sunken px-2 py-0.5 [overflow-wrap:anywhere]"
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
        <Button
          variant="secondary"
          size="sm"
          type="button"
          disabled={full || !text.trim()}
          onClick={add}
        >
          Add
        </Button>
      </div>
      {hint && (
        <p id={hintId} className="mt-1 text-ink-muted">
          {hint}
        </p>
      )}
    </div>
  );
}
