import type { ReactNode } from "react";

const GRID = {
  // Label/description left, control right.
  split: "sm:grid-cols-[minmax(0,1fr)_minmax(180px,0.9fr)] sm:items-start sm:gap-6",
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
        {description && <div className="mt-1 text-xs text-ink-muted">{description}</div>}
      </div>
      <div
        className={layout === "action" ? "flex min-w-0 flex-wrap gap-2 sm:justify-end" : "min-w-0"}
      >
        {children}
      </div>
    </div>
  );
}
