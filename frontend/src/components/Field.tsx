/**
 * Shared label+control primitives, extracted from RunPage's SettingsPanel so
 * VocabularyPage's pack editor can reuse the same look without duplicating them.
 * The `.field` class both `Field`'s children and SettingsPanel's raw inputs rely
 * on lives in `index.css`, not here — it styles the input/select itself, which
 * callers apply directly rather than through this wrapper.
 */
import type { ReactNode } from "react";

export function Field({
  label,
  help,
  children,
}: {
  label: ReactNode;
  help?: string;
  children: ReactNode;
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
  disabled,
  disabledHint,
  onChange,
}: {
  label: string;
  help?: string;
  checked: boolean;
  disabled?: boolean;
  /** Shown instead of `help` when the control is disabled — explains why. */
  disabledHint?: string;
  onChange: (v: boolean) => void;
}) {
  return (
    <label className="flex cursor-pointer gap-2 text-sm">
      <input
        type="checkbox"
        checked={checked}
        disabled={disabled}
        onChange={(e) => onChange(e.target.checked)}
        className="mt-0.5 accent-[var(--color-accent)] disabled:opacity-50"
      />
      <span>
        <span className="font-medium">{label}</span>
        {(disabled ? disabledHint : help) && (
          <span className="mt-0.5 block text-xs text-ink-muted">
            {disabled ? disabledHint : help}
          </span>
        )}
      </span>
    </label>
  );
}
