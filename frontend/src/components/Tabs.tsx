import { type KeyboardEvent, useEffect, useRef } from "react";
import { SEGMENT_BASE, SEGMENT_OFF, SEGMENT_ON, SEGMENT_TRACK } from "./ui/Segmented";

type TabItem = { id: string; label: string; count?: number };

/** Shared appearance for page-section tabs and Profile's section links. */
export function underlineTabClass(active: boolean): string {
  return `rt-control -mb-px border-b px-3 py-2 text-sm ${active ? "border-selected-line font-semibold text-ink" : "border-transparent text-ink-muted hover:text-ink"}`;
}

/**
 * ARIA tabs (tablist/tab/aria-selected, roving tabindex, arrow/Home/End keys).
 * `variant="underline"` (default) is the page-level look: muted text, ink when selected,
 * an accent border. `variant="segmented"` is a contained control with the green
 * `selected` look, for switching a panel's view. `orientation="vertical"` stacks the tabs
 * as a side rail (Up/Down move). The roles and keyboard contract are identical in every
 * combination. A horizontal strip that overflows narrow screens scrolls the selected tab
 * into view on mount and whenever the selection changes.
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
  const list = useRef<HTMLDivElement>(null);
  useEffect(() => {
    // Scroll only the strip, never the page (scrollIntoView would also move the window
    // when the tablist sits below the fold). jsdom reports zero widths, so it is a no-op.
    const strip = list.current;
    const tab = strip?.querySelector<HTMLElement>('[role="tab"][aria-selected="true"]');
    if (!strip || !tab || strip.scrollWidth <= strip.clientWidth) return;
    const box = strip.getBoundingClientRect();
    const rect = tab.getBoundingClientRect();
    if (rect.left < box.left) strip.scrollLeft -= box.left - rect.left;
    else if (rect.right > box.right) strip.scrollLeft += rect.right - box.right;
  }, [value]);
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
  // When no tab matches `value`, the first one keeps the tablist in the Tab order.
  const stop = items.some((item) => item.id === value) ? value : items[0]?.id;
  const track = segmented
    ? `${SEGMENT_TRACK} ${vertical ? "flex-col" : ""}`
    : vertical
      ? "flex flex-col gap-0.5"
      : "-mb-px flex gap-4 overflow-x-auto pb-px [scrollbar-width:none]";
  const tabList = (
    <div
      ref={list}
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
            : `${underlineTabClass(on)} shrink-0 whitespace-nowrap`;
        return (
          <button
            type="button"
            key={item.id}
            role="tab"
            data-tab={item.id}
            aria-selected={on}
            tabIndex={item.id === stop ? 0 : -1}
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
  // Keep the hairline outside the scroll strip so -mb-px can overlap it without
  // the strip clipping the active tab's border.
  return !segmented && !vertical ? (
    <div className="min-w-0 border-b border-line">{tabList}</div>
  ) : (
    tabList
  );
}
