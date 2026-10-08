import { useId, useState } from "react";

type StylePromptFieldProps = {
  label: string;
  help: string;
  value: string | null;
  defaultText: string;
  lockedCoreRules: string;
  onChange: (value: string | null) => void;
};

/**
 * Editable style block for one LLM writing stage, with a read-only locked-core
 * preview. Deliberately not built on the shared `Field` component: `Field` wraps its
 * children in a single `<label>`, which is correct for a label+single-control pair
 * but wrong here — with the "Locked safety rules" and "Reset to default" buttons also
 * inside it, clicking either would implicitly re-target the textarea too. The label
 * below is instead explicitly associated with just the textarea via `htmlFor`/`id`.
 */
export function StylePromptField({
  label,
  help,
  value,
  defaultText,
  lockedCoreRules,
  onChange,
}: StylePromptFieldProps) {
  const [coreOpen, setCoreOpen] = useState(false);
  const textareaId = useId();
  const coreId = useId();
  const customized = value !== null;
  const displayText = value ?? defaultText;

  /** Clear the override so the next run uses the shipped default again. */
  function resetToDefault() {
    onChange(null);
  }

  return (
    <div className="block text-sm">
      <label htmlFor={textareaId} className="mb-1 block text-ink-muted">
        <span className="inline-flex items-center gap-2">
          {label}
          {customized && (
            <span className="font-mono text-micro uppercase tracking-[0.08em] text-accent">
              Customized
            </span>
          )}
        </span>
      </label>
      <textarea
        id={textareaId}
        rows={12}
        value={displayText}
        onChange={(e) => onChange(e.target.value)}
        className="field resize-y font-mono text-xs leading-relaxed"
      />
      {help && <span className="mt-1 block text-xs text-ink-muted">{help}</span>}
      <div className="mt-2 flex items-center justify-between gap-3">
        <button
          type="button"
          onClick={() => setCoreOpen((open) => !open)}
          aria-expanded={coreOpen}
          aria-controls={coreId}
          className="text-xs text-ink-muted underline-offset-2 hover:text-ink hover:underline"
        >
          Locked safety rules {coreOpen ? "▾" : "▸"}
        </button>
        {customized && (
          <button
            type="button"
            onClick={resetToDefault}
            className="text-xs text-ink-muted underline-offset-2 hover:text-ink hover:underline"
          >
            Reset to default
          </button>
        )}
      </div>
      {coreOpen && (
        <pre
          id={coreId}
          className="mt-2 max-h-48 overflow-auto rounded-sm bg-sunken p-3 font-mono text-xs leading-relaxed whitespace-pre-wrap text-ink-2"
        >
          {lockedCoreRules}
        </pre>
      )}
    </div>
  );
}
