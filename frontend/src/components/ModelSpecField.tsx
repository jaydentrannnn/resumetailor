import { useState } from "react";
import { useModelSpecs } from "../lib/modelSpecs";

/**
 * Select + add/remove row for a model override, backed by the shared saved-spec list.
 *
 * Specs added here appear immediately in every other ModelSpecField (rewrite and expand
 * share one list). An unknown current value is still shown as an option so a restored
 * session is not silently cleared.
 */
export function ModelSpecField({
  label,
  value,
  onChange,
  placeholder,
}: {
  label: string;
  value: string | null;
  onChange: (next: string | null) => void;
  placeholder?: string;
}) {
  const { specs, addSpec, removeSpec } = useModelSpecs();
  const [draft, setDraft] = useState("");

  const options =
    value && !specs.includes(value) ? [...specs, value] : specs;

  function onAdd() {
    /** Save the draft into the shared list and select it. */
    const trimmed = draft.trim();
    if (!trimmed) return;
    addSpec(trimmed);
    onChange(trimmed);
    setDraft("");
  }

  function onRemoveSelected() {
    /** Remove the currently selected spec from the shared list and clear the field. */
    if (!value) return;
    removeSpec(value);
    onChange(null);
  }

  return (
    <div className="block text-sm">
      <span className="mb-1 block text-ink-muted">{label}</span>
      <select
        value={value ?? ""}
        onChange={(e) => onChange(e.target.value || null)}
        className="field"
      >
        <option value="">Use profile default</option>
        {options.map((spec) => (
          <option key={spec} value={spec}>
            {spec}
          </option>
        ))}
      </select>
      <div className="mt-2 flex gap-2">
        <input
          type="text"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              e.preventDefault();
              onAdd();
            }
          }}
          placeholder={placeholder ?? "e.g. claude-sonnet-5"}
          className="field min-w-0 flex-1"
        />
        <button
          type="button"
          onClick={onAdd}
          disabled={!draft.trim()}
          className="shrink-0 rounded-md border border-line px-2.5 py-1 text-xs font-medium text-ink-muted hover:border-accent hover:text-accent disabled:opacity-40"
        >
          Add
        </button>
        <button
          type="button"
          onClick={onRemoveSelected}
          disabled={!value}
          className="shrink-0 rounded-md border border-line px-2.5 py-1 text-xs font-medium text-ink-muted hover:border-danger hover:text-danger disabled:opacity-40"
        >
          Remove
        </button>
      </div>
    </div>
  );
}
