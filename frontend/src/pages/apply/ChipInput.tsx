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
