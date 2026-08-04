/**
 * Shared label+control primitives, extracted from RunPage's SettingsPanel so
 * SettingsPage's pack editor can reuse the same look without duplicating them.
 * The `.field` class both `Field`'s children and SettingsPanel's raw inputs rely
 * on lives in `index.css`, not here — it styles the input/select itself, which
 * callers apply directly rather than through this wrapper.
 */
export function Field({
  label,
  help,
  children,
}: {
  label: string;
  help?: string;
  children: React.ReactNode;
}) {
  return (
    <label className="block text-sm">
      <span className="mb-1 block text-ink-muted">{label}</span>
      {children}
      {help && <span className="mt-1 block text-xs text-ink-muted">{help}</span>}
    </label>
  );
}

export function Toggle({
  label,
  help,
  checked,
  onChange,
}: {
  label: string;
  help?: string;
  checked: boolean;
  onChange: (v: boolean) => void;
}) {
  return (
    <label className="flex cursor-pointer gap-2 text-sm">
      <input
        type="checkbox"
        checked={checked}
        onChange={(e) => onChange(e.target.checked)}
        className="mt-0.5 accent-[var(--color-accent)]"
      />
      <span>
        <span className="font-medium">{label}</span>
        {help && <span className="mt-0.5 block text-xs text-ink-muted">{help}</span>}
      </span>
    </label>
  );
}
