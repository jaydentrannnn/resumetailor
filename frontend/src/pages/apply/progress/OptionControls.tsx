import type { ReactNode } from "react";
import { Segmented } from "../../../components/ui";

/**
 * A banner's option groups: three columns side by side in the customize dialog
 * (`columns`), stacked otherwise. Each child is one `OptionGroup`.
 */
export function OptionColumns({ columns, children }: { columns: boolean; children: ReactNode }) {
  return (
    <div className={columns ? "grid gap-x-8 gap-y-5 md:grid-cols-3" : "space-y-4"}>{children}</div>
  );
}

/** One column of options, stacked top to bottom. */
export function OptionGroup({ children }: { children: ReactNode }) {
  return <div className="min-w-0 space-y-4">{children}</div>;
}

/** One labelled option in Apply settings › Progress banner. */
export function OptionField({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="space-y-1.5">
      <p className="text-xs font-medium text-ink-2">{label}</p>
      {children}
    </div>
  );
}

/** A labelled Segmented over a fixed list of choices. */
export function OptionChoice<T extends string>({
  label,
  items,
  value,
  onChange,
}: {
  label: string;
  items: { id: T; label: string }[];
  value: T;
  onChange: (id: T) => void;
}) {
  return (
    <OptionField label={label}>
      <Segmented label={label} items={items} value={value} onChange={(id) => onChange(id as T)} />
    </OptionField>
  );
}

/** A labelled dropdown, for choices too many or too long for a Segmented. */
export function OptionSelect<T extends string>({
  label,
  items,
  value,
  onChange,
}: {
  label: string;
  items: { id: T; label: string }[];
  value: T;
  onChange: (id: T) => void;
}) {
  return (
    <OptionField label={label}>
      <select
        aria-label={label}
        className="field w-full max-w-60"
        value={value}
        onChange={(e) => onChange(e.target.value as T)}
      >
        {items.map((item) => (
          <option key={item.id} value={item.id}>
            {item.label}
          </option>
        ))}
      </select>
    </OptionField>
  );
}

/** Checkboxes for the parts a banner shows; a disabled one has no effect in this style. */
export function ShowParts({
  items,
}: {
  items: { label: string; checked: boolean; disabled?: boolean; onChange: (on: boolean) => void }[];
}) {
  return (
    <OptionField label="Show">
      <div className="flex flex-col gap-2">
        {items.map((item) => (
          <label
            key={item.label}
            className={`flex items-center gap-2 text-sm ${item.disabled ? "text-ink-muted" : ""}`}
          >
            <input
              type="checkbox"
              className="h-4 w-4 accent-[var(--color-accent)]"
              checked={item.checked}
              disabled={item.disabled}
              onChange={(e) => item.onChange(e.target.checked)}
            />
            {item.label}
          </label>
        ))}
      </div>
    </OptionField>
  );
}

/** From and to days for a custom range (both ends included). */
export function DateRangeFields({
  start,
  end,
  onChange,
}: {
  start: string | null;
  end: string | null;
  onChange: (range: { start: string | null; end: string | null }) => void;
}) {
  const incomplete = !start || !end;
  return (
    <div className="space-y-1">
      <div className="flex flex-wrap items-end gap-3">
        <label className="block">
          <span className="mb-1 block text-xs text-ink-2">From</span>
          <input
            type="date"
            className="field"
            value={start ?? ""}
            onChange={(e) => onChange({ start: e.target.value || null, end })}
          />
        </label>
        <label className="block">
          <span className="mb-1 block text-xs text-ink-2">To</span>
          <input
            type="date"
            className="field"
            value={end ?? ""}
            onChange={(e) => onChange({ start, end: e.target.value || null })}
          />
        </label>
      </div>
      {incomplete && (
        <p className="text-xs text-ink-muted">
          Pick both days; until then the banner shows its default range.
        </p>
      )}
    </div>
  );
}
