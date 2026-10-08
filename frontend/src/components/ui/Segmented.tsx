import { type KeyboardEvent, type ReactNode } from "react";

export interface SegmentedItem {
  id: string;
  label: ReactNode;
  /** Mono count shown after the label, e.g. a tab's row count. */
  count?: number;
  disabled?: boolean;
}

/** Shared look of a segment; `Tabs variant="segmented"` reuses it. */
export const SEGMENT_TRACK =
  "inline-flex flex-wrap gap-0.5 rounded-md border border-line bg-sunken p-[3px]";
export const SEGMENT_BASE =
  "rt-row-action inline-flex items-center gap-1.5 whitespace-nowrap rounded-sm px-3 text-xs font-medium transition-colors duration-[var(--dur-short)] disabled:opacity-50";
export const SEGMENT_ON =
  "bg-selected text-on-selected shadow-[inset_0_0_0_1px_var(--color-selected-line)]";
export const SEGMENT_OFF = "text-ink-muted hover:text-ink";

/**
 * A one-of-N choice as a radiogroup (theme, view mode, filter). Selected = solid green in
 * light, mint outline + wash in dark (`selected` tokens). Arrow keys move and select.
 * For content panels use `Tabs variant="segmented"` instead.
 */
export function Segmented({
  items,
  value,
  onChange,
  label,
  className = "",
}: {
  items: SegmentedItem[];
  value: string;
  onChange: (id: string) => void;
  /** Accessible name of the group. */
  label: string;
  className?: string;
}) {
  function onKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    const enabled = items.filter((item) => !item.disabled);
    const at = enabled.findIndex((item) => item.id === value);
    const step =
      event.key === "ArrowRight" || event.key === "ArrowDown"
        ? 1
        : event.key === "ArrowLeft" || event.key === "ArrowUp"
          ? -1
          : 0;
    if (!step || !enabled.length) return;
    event.preventDefault();
    const next = enabled[(Math.max(at, 0) + step + enabled.length) % enabled.length];
    onChange(next.id);
    (event.currentTarget.querySelector(`[data-seg="${next.id}"]`) as HTMLElement | null)?.focus();
  }
  return (
    <div
      role="radiogroup"
      aria-label={label}
      className={`${SEGMENT_TRACK} ${className}`.trim()}
      onKeyDown={onKeyDown}
    >
      {items.map((item) => {
        const on = item.id === value;
        return (
          <button
            type="button"
            key={item.id}
            role="radio"
            data-seg={item.id}
            aria-checked={on}
            disabled={item.disabled}
            tabIndex={on ? 0 : -1}
            className={`${SEGMENT_BASE} ${on ? SEGMENT_ON : SEGMENT_OFF}`}
            onClick={() => onChange(item.id)}
          >
            {item.label}
            {item.count != null && (
              <span className="font-mono text-micro opacity-80">{item.count}</span>
            )}
          </button>
        );
      })}
    </div>
  );
}
