export function TextField({
  label,
  value,
  onChange,
  type = "text",
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  /** "month" renders the browser's month picker (value `YYYY-MM`). */
  type?: "text" | "month";
}) {
  return (
    <label className="block text-sm">
      <span className="mb-1 block text-ink-muted">{label}</span>
      <input
        type={type}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="w-full rounded-md border border-line bg-paper/40 px-2 py-1.5 text-sm focus:border-accent"
      />
    </label>
  );
}
