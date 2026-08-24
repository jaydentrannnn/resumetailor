import { useState } from "react";
import { Field } from "./Field";

type StylePromptFieldProps = {
  label: string;
  help: string;
  value: string | null;
  defaultText: string;
  lockedCoreRules: string;
  onChange: (value: string | null) => void;
};

/** Editable style block for one LLM writing stage, with a read-only locked-core preview. */
export function StylePromptField({
  label,
  help,
  value,
  defaultText,
  lockedCoreRules,
  onChange,
}: StylePromptFieldProps) {
  const [coreOpen, setCoreOpen] = useState(false);
  const customized = value !== null;
  const displayText = value ?? defaultText;

  /** Clear the override so the next run uses the shipped default again. */
  function resetToDefault() {
    onChange(null);
  }

  return (
    <Field
      label={
        <span className="inline-flex items-center gap-2">
          {label}
          {customized && (
            <span className="rounded bg-accent/15 px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-accent">
              Customized
            </span>
          )}
        </span>
      }
      help={help}
    >
      <textarea
        rows={12}
        value={displayText}
        onChange={(e) => onChange(e.target.value)}
        className="w-full resize-y rounded-lg border border-line bg-paper/40 px-3 py-2 font-mono text-xs leading-relaxed focus:border-accent focus:outline-none focus:ring-1 focus:ring-accent/30"
      />
      <div className="mt-2 flex items-center justify-between gap-3">
        <button
          type="button"
          onClick={() => setCoreOpen((open) => !open)}
          className="text-xs text-ink-muted underline-offset-2 hover:text-accent hover:underline"
        >
          Locked safety rules {coreOpen ? "▾" : "▸"}
        </button>
        {customized && (
          <button
            type="button"
            onClick={resetToDefault}
            className="text-xs text-ink-muted underline-offset-2 hover:text-accent hover:underline"
          >
            Reset to default
          </button>
        )}
      </div>
      {coreOpen && (
        <pre className="mt-2 max-h-48 overflow-auto rounded-md border border-line bg-paper/60 p-3 font-mono text-[11px] leading-relaxed text-ink-muted whitespace-pre-wrap">
          {lockedCoreRules}
        </pre>
      )}
    </Field>
  );
}
