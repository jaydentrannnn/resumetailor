import type { ReactNode } from "react";

/**
 * A determinate or indeterminate progress bar (`role=progressbar`). `label` is the
 * accessible name; `valueText` is what a screen reader announces ("Step 3 of 6").
 * The track is the one place `rounded-full` is allowed (a 4px-high bar reads as a line).
 */
export function Meter({
  value,
  label,
  valueText,
  indeterminate = false,
  tone = "accent",
  className = "",
}: {
  /** 0–100; ignored while `indeterminate`. */
  value?: number;
  label: string;
  valueText?: string;
  indeterminate?: boolean;
  tone?: "accent" | "danger" | "ink";
  className?: string;
}) {
  const pct = Math.max(0, Math.min(100, value ?? 0));
  const fill = tone === "danger" ? "bg-danger" : tone === "ink" ? "bg-ink-2" : "bg-accent";
  return (
    <div
      role="progressbar"
      aria-label={label}
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={indeterminate ? undefined : Math.round(pct)}
      aria-valuetext={valueText}
      className={`h-1 overflow-hidden rounded-full bg-sunken ${className}`.trim()}
    >
      {indeterminate ? (
        <div
          className={`rt-progress-indeterminate h-full w-1/3 rounded-full ${fill} [animation:rt-progress-slide_1.2s_var(--ease-in-out)_infinite]`}
        />
      ) : (
        <div
          className={`h-full rounded-full ${fill} transition-[width] duration-[var(--dur-base)] ease-out`}
          style={{ width: `${pct}%` }}
        />
      )}
    </div>
  );
}

export interface DataItem {
  label: ReactNode;
  value: ReactNode;
}

/**
 * Label/value pairs as a `<dl>`, separated by spacing only (no divider lines, no cells).
 * `mono` sets values in Geist Mono for times, counts, IDs and model names.
 */
export function DataList({
  items,
  mono = false,
  className = "",
}: {
  items: DataItem[];
  mono?: boolean;
  className?: string;
}) {
  return (
    <dl className={`m-0 flex flex-wrap gap-x-8 gap-y-3 ${className}`.trim()}>
      {items.map((item, index) => (
        <div key={index} className="grid min-w-0 gap-1">
          <dt className="rt-eyebrow">{item.label}</dt>
          <dd
            className={`m-0 text-[15px] font-medium text-ink [overflow-wrap:anywhere] ${mono ? "font-mono text-[13px] tabular-nums" : ""}`}
          >
            {item.value}
          </dd>
        </div>
      ))}
    </dl>
  );
}

/** A big serif figure with a quiet caption ("82" / "skill match out of 100"). */
export function Stat({
  value,
  label,
  className = "",
}: {
  value: ReactNode;
  label: ReactNode;
  className?: string;
}) {
  return (
    <div className={`grid min-w-0 gap-1.5 ${className}`.trim()}>
      <span className="rt-figure">{value}</span>
      <span className="text-xs text-ink-muted">{label}</span>
    </div>
  );
}

/**
 * The contextual toolbar above a table or list while rows are selected: mono count,
 * the bulk actions, and Clear. Render it only when `count > 0`. `label` is the toolbar's
 * accessible name.
 */
export function SelectionBar({
  count,
  noun = "selected",
  onClear,
  clearLabel = "Clear selection",
  label = "Selection actions",
  children,
  className = "",
}: {
  count: number;
  noun?: string;
  onClear: () => void;
  clearLabel?: string;
  /** The toolbar's aria-label. */
  label?: string;
  /** Bulk-action buttons. */
  children?: ReactNode;
  className?: string;
}) {
  return (
    <div
      role="toolbar"
      aria-label={label}
      className={`flex flex-wrap items-center gap-2 rounded-sm border border-selected-line/40 bg-accent-soft px-3.5 py-1.5 text-[13px] ${className}`.trim()}
    >
      <strong className="mr-auto font-semibold">
        <span className="font-mono tabular-nums">{count}</span> {noun}
      </strong>
      {children}
      <button
        type="button"
        onClick={onClear}
        className="rt-row-action rounded-sm px-3 text-xs font-medium text-ink-muted hover:bg-sunken hover:text-ink"
      >
        {clearLabel}
      </button>
    </div>
  );
}
