import type { TrackerColumn } from "../../api";
import { TRACKER_COLUMNS, type TrackerFilters as Filters } from "../../lib/tracker";

/**
 * Search, the "sent from → until" range, emails only, and the hidden columns (shown as
 * chips to bring back; a column hides from its own header).
 */
export function TrackerFilters({
  filters,
  onChange,
  hidden,
  onShow,
}: {
  filters: Filters;
  onChange: (next: Filters) => void;
  hidden: TrackerColumn[];
  onShow: (column: TrackerColumn) => void;
}) {
  const set = (patch: Partial<Filters>) => onChange({ ...filters, ...patch });
  return (
    <div className="flex flex-wrap items-center gap-2 text-xs">
      <input
        type="search"
        className="field rt-control w-64 max-w-full py-0"
        aria-label="Search the tracker"
        data-shortcut="search"
        placeholder="Search company, role or location"
        value={filters.q}
        onChange={(e) => set({ q: e.target.value })}
      />
      <label className="flex items-center gap-1.5 text-ink-2">
        Sent from
        <input
          type="date"
          className="field rt-control w-auto py-0"
          value={filters.from}
          onChange={(e) => set({ from: e.target.value })}
        />
      </label>
      <label className="flex items-center gap-1.5 text-ink-2">
        until
        <input
          type="date"
          className="field rt-control w-auto py-0"
          value={filters.until}
          onChange={(e) => set({ until: e.target.value })}
        />
      </label>
      <label className="flex items-center gap-1.5 text-ink-2">
        <input
          type="checkbox"
          checked={filters.email}
          onChange={(e) => set({ email: e.target.checked })}
        />
        With email updates
      </label>
      {hidden.length > 0 && (
        <span className="flex flex-wrap items-center gap-1.5 text-ink-muted">
          Hidden columns:
          {TRACKER_COLUMNS.filter((c) => hidden.includes(c.id)).map((c) => (
            <button
              key={c.id}
              type="button"
              className="rt-row-action rounded-sm border border-line px-2 text-ink-2 hover:border-line-hover hover:text-ink"
              aria-label={`Show ${c.label}`}
              onClick={() => onShow(c.id)}
            >
              Show {c.label}
            </button>
          ))}
        </span>
      )}
    </div>
  );
}
