import type { ReactNode } from "react";

/**
 * The label column every label-left row shares, so controls line up down a page. On
 * wide screens it takes a third of the row, so a stretched window spreads the rows out
 * instead of leaving the right side empty.
 */
export const ROW_LABEL_COLUMN =
  "sm:grid-cols-[minmax(0,17rem)_minmax(0,1fr)] 2xl:grid-cols-[minmax(17rem,1fr)_minmax(0,2fr)]";

const GRID = {
  // Label/description in a fixed column on the left, the control beside it.
  split: `${ROW_LABEL_COLUMN} sm:items-center sm:gap-8`,
  // Label/description on top, the control full width underneath.
  stacked: "",
  // Text takes the room it needs on the left; buttons sit right-aligned at the end.
  action: "sm:grid-cols-[minmax(0,1fr)_auto] sm:items-center sm:gap-6",
} as const;

/** Label/description and control, separated by spacing and a single row hairline. */
export function SettingRow({
  label,
  description,
  layout = "split",
  children,
}: {
  label: ReactNode;
  description?: ReactNode;
  layout?: keyof typeof GRID;
  children: ReactNode;
}) {
  return (
    <div
      className={`grid min-w-0 gap-3 border-t border-line py-4 first:border-0 first:pt-0 last:pb-0 ${GRID[layout]}`.trim()}
    >
      <div className="min-w-0">
        <p className="text-sm font-medium">{label}</p>
        {description && (
          <div className="mt-1 max-w-[80ch] text-xs text-ink-muted">{description}</div>
        )}
      </div>
      <div
        className={
          layout === "stacked"
            ? "min-w-0"
            : `flex min-w-0 flex-wrap items-center gap-2 ${layout === "action" ? "sm:justify-end" : ""}`
        }
      >
        {children}
      </div>
    </div>
  );
}
