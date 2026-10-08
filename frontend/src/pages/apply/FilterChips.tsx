/** A row of toggle chips; every pressed chip is "any of" within its own group. */
export function FilterChips<T extends string>({
  label,
  options,
  labels,
  selected,
  onChange,
}: {
  label: string;
  options: T[];
  labels: Record<T, string>;
  selected: T[];
  onChange: (next: T[]) => void;
}) {
  if (options.length === 0) return null;
  return (
    <div role="group" aria-label={label} className="flex flex-wrap gap-1.5">
      {options.map((option) => {
        const on = selected.includes(option);
        return (
          <button
            key={option}
            type="button"
            aria-pressed={on}
            className={`rounded-sm border px-2.5 py-0.5 text-xs ${on ? "border-selected-line bg-selected text-on-selected" : "border-line text-ink-muted hover:border-accent"}`}
            onClick={() => onChange(on ? selected.filter((o) => o !== option) : [...selected, option])}
          >
            {labels[option]}
          </button>
        );
      })}
    </div>
  );
}
