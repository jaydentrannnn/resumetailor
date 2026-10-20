import type { ReactNode } from "react";
import { Segmented } from "../../../components/ui";

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

/** Checkboxes for the parts a banner shows; a disabled one has no effect in this style. */
export function ShowParts({
  items,
}: {
  items: { label: string; checked: boolean; disabled?: boolean; onChange: (on: boolean) => void }[];
}) {
  return (
    <OptionField label="Show">
      <div className="flex flex-wrap gap-x-5 gap-y-2">
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
