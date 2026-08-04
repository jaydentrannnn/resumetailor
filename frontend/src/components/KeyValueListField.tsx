import { useState } from "react";

type KeyValueListFieldProps = {
  label: string;
  keyPlaceholder?: string;
  valuePlaceholder?: string;
  items: Record<string, string>;
  onChange: (items: Record<string, string>) => void;
};

/**
 * Editable key -> value rows for a flat string map (a pack's `tag_aliases`, or an
 * override's verb -> family map). Existing rows commit on blur; a trailing draft row
 * commits on Enter or the Add button. Not built on `ChipListField` — that component
 * is for a plain string *set*, and this needs two columns per row.
 */
export function KeyValueListField({
  label,
  keyPlaceholder = "key",
  valuePlaceholder = "value",
  items,
  onChange,
}: KeyValueListFieldProps) {
  const entries = Object.entries(items);
  const [draftKey, setDraftKey] = useState("");
  const [draftValue, setDraftValue] = useState("");

  function updateEntry(oldKey: string, newKey: string, newValue: string) {
    const trimmedKey = newKey.trim();
    const next = { ...items };
    if (oldKey !== trimmedKey) delete next[oldKey];
    if (trimmedKey) next[trimmedKey] = newValue.trim();
    onChange(next);
  }

  function removeEntry(key: string) {
    const next = { ...items };
    delete next[key];
    onChange(next);
  }

  function addDraft() {
    const key = draftKey.trim();
    if (!key) return;
    onChange({ ...items, [key]: draftValue.trim() });
    setDraftKey("");
    setDraftValue("");
  }

  return (
    <div className="text-sm">
      <span className="mb-1 block text-ink-muted">{label}</span>
      <div className="space-y-1.5">
        {entries.map(([k, v]) => (
          <div key={k} className="flex items-center gap-1.5">
            <input
              type="text"
              defaultValue={k}
              onBlur={(e) => updateEntry(k, e.target.value, v)}
              className="field flex-1"
            />
            <span className="text-ink-muted">&rarr;</span>
            <input
              type="text"
              defaultValue={v}
              onBlur={(e) => updateEntry(k, k, e.target.value)}
              className="field flex-1"
            />
            <button
              type="button"
              onClick={() => removeEntry(k)}
              title={`Remove ${k}`}
              className="rounded-full px-1.5 text-ink-muted hover:text-danger"
            >
              ×
            </button>
          </div>
        ))}
        <div className="flex items-center gap-1.5">
          <input
            type="text"
            placeholder={keyPlaceholder}
            value={draftKey}
            onChange={(e) => setDraftKey(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                e.preventDefault();
                addDraft();
              }
            }}
            className="field flex-1"
          />
          <span className="text-ink-muted">&rarr;</span>
          <input
            type="text"
            placeholder={valuePlaceholder}
            value={draftValue}
            onChange={(e) => setDraftValue(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                e.preventDefault();
                addDraft();
              }
            }}
            className="field flex-1"
          />
          <button
            type="button"
            onClick={addDraft}
            className="rounded-md border border-line px-2 py-1 text-xs text-ink-muted hover:border-accent hover:text-accent"
          >
            Add
          </button>
        </div>
      </div>
    </div>
  );
}
