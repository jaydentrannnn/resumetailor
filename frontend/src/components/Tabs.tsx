import { type KeyboardEvent } from "react";
import { SEGMENT_BASE, SEGMENT_OFF, SEGMENT_ON, SEGMENT_TRACK } from "./ui/Segmented";

type TabItem = { id: string; label: string; count?: number };

/**
 * ARIA tabs (tablist/tab/aria-selected, roving tabindex, arrow/Home/End keys).
 * `variant="underline"` (default) is the page-level look: muted text, ink when selected,
 * a 2px accent underline. `variant="segmented"` is a contained control with the green
 * `selected` look, for switching a panel's view. `orientation="vertical"` stacks the tabs
 * as a side rail (Up/Down move). The roles and keyboard contract are identical in every
 * combination.
 */
export function Tabs({
  items,
  value,
  onChange,
  label,
  variant = "underline",
  orientation = "horizontal",
}: {
  items: TabItem[];
  value: string;
  onChange: (id: string) => void;
  label: string;
  variant?: "underline" | "segmented";
  orientation?: "horizontal" | "vertical";
}) {
  const vertical = orientation === "vertical";
  function onKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    const current = Math.max(
      0,
      items.findIndex((item) => item.id === value),
    );
    const forward = vertical ? "ArrowDown" : "ArrowRight";
    const back = vertical ? "ArrowUp" : "ArrowLeft";
    const next =
      event.key === forward
        ? items[(current + 1) % items.length]
        : event.key === back
          ? items[(current + items.length - 1) % items.length]
          : event.key === "Home"
            ? items[0]
            : event.key === "End"
              ? items[items.length - 1]
              : null;
    if (!next) return;
    event.preventDefault();
    onChange(next.id);
    (event.currentTarget.querySelector(`[data-tab="${next.id}"]`) as HTMLElement | null)?.focus();
  }
  const segmented = variant === "segmented";
  const track = segmented
    ? `${SEGMENT_TRACK} ${vertical ? "flex-col" : ""}`
    : vertical
      ? "flex flex-col gap-0.5"
      : "flex gap-1 overflow-x-auto border-b border-line [scrollbar-width:none]";
  return (
    <div
      role="tablist"
      aria-label={label}
      aria-orientation={vertical ? "vertical" : undefined}
      className={track}
      onKeyDown={onKeyDown}
    >
      {items.map((item) => {
        const on = value === item.id;
        const look = segmented
          ? `${SEGMENT_BASE} ${on ? SEGMENT_ON : SEGMENT_OFF}`
          : vertical
            ? `flex items-center justify-between gap-2 rounded-sm px-3 py-2 text-left text-[13px] font-medium ${on ? "bg-panel text-ink shadow-[inset_2px_0_0_var(--color-accent)]" : "text-ink-muted hover:bg-sunken hover:text-ink"}`
            : `relative h-10 shrink-0 whitespace-nowrap px-3 text-[13px] font-medium after:absolute after:inset-x-3 after:-bottom-px after:h-0.5 ${on ? "text-ink after:bg-accent" : "text-ink-muted after:bg-transparent hover:text-ink"}`;
        return (
          <button
            type="button"
            key={item.id}
            role="tab"
            data-tab={item.id}
            aria-selected={on}
            tabIndex={on ? 0 : -1}
            className={look}
            onClick={() => onChange(item.id)}
          >
            {item.label}
            {item.count != null && (
              <span
                className={`font-mono text-micro ${segmented ? "opacity-80" : "text-ink-muted"}`}
              >
                {item.count}
              </span>
            )}
          </button>
        );
      })}
    </div>
  );
}
