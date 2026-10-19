/** Filters the editor's entries by their text ("/" or, in the desktop app, Ctrl+F). */
export function EntryFilterField({
  value,
  onChange,
}: {
  value: string;
  onChange: (value: string) => void;
}) {
  return (
    <div className="relative w-full sm:w-56">
      <input
        className="field rt-control py-0 pr-8"
        aria-label="Filter resume entries"
        data-shortcut="search"
        placeholder="Filter entries"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Escape" && value) {
            e.stopPropagation();
            onChange("");
          }
        }}
      />
      {value && (
        <button
          type="button"
          aria-label="Clear filter"
          className="absolute right-1 top-1/2 -translate-y-1/2 px-1.5 text-ink-muted hover:text-ink"
          onClick={() => onChange("")}
        >
          ×
        </button>
      )}
    </div>
  );
}
