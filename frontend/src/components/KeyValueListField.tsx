import { useRef, useState } from "react";

type Row = { rowId: string; key: string; value: string };

let nextRowId = 0;
function newRowId(): string {
  return `kv-${nextRowId++}`;
}

function rowsFrom(items: Record<string, string>): Row[] {
  return Object.entries(items).map(([key, value]) => ({ rowId: newRowId(), key, value }));
}

function recordFrom(rows: Row[]): Record<string, string> {
  const out: Record<string, string> = {};
  for (const row of rows) {
    const key = row.key.trim();
    if (key) out[key] = row.value.trim();
  }
  return out;
}

/** Order-sensitive: a server-side reorder should re-sync the rows, not be swallowed. */
function sameRecord(a: Record<string, string>, b: Record<string, string>): boolean {
  const ak = Object.keys(a);
  const bk = Object.keys(b);
  if (ak.length !== bk.length) return false;
  for (let i = 0; i < ak.length; i++) {
    if (ak[i] !== bk[i] || a[ak[i]] !== b[bk[i]]) return false;
  }
  return true;
}

/** rowId -> message, for a duplicate key or a value typed with no key yet. A fully
 * blank row is not an error — it just contributes nothing to the emitted record. */
function rowErrors(rows: Row[]): Map<string, string> {
  const errors = new Map<string, string>();
  const counts = new Map<string, number>();
  for (const row of rows) {
    const key = row.key.trim();
    if (key) counts.set(key, (counts.get(key) ?? 0) + 1);
  }
  for (const row of rows) {
    const key = row.key.trim();
    if (!key && row.value.trim()) {
      errors.set(row.rowId, "Needs a key.");
    } else if (key && (counts.get(key) ?? 0) > 1) {
      errors.set(row.rowId, `Duplicate key "${key}".`);
    }
  }
  return errors;
}

type KeyValueListFieldProps = {
  label: string;
  keyPlaceholder?: string;
  valuePlaceholder?: string;
  items: Record<string, string>;
  onChange: (items: Record<string, string>) => void;
  /** Optional external error lookup keyed by a row's current (trimmed) key — e.g. a
   * pack-validation message such as a self-alias or a chain. Rendered the same way as
   * this component's own duplicate/empty-key errors, with those taking priority. */
  errorFor?: (key: string) => string | null | undefined;
  /** When non-empty, only rows whose key or value contains this (case-insensitively)
   * are rendered. Hidden rows stay in internal state and are still emitted — this
   * narrows the view only, it never drops data. */
  filterText?: string;
};

/**
 * Editable key -> value rows for a flat string map (a pack's `tag_aliases`, or an
 * override's verb -> family map). Rows hold their own text while typing and only
 * notify the parent on blur/add/remove — never per keystroke, since every caller here
 * turns `onChange` straight into a `PUT`. Re-syncs from `items` only when its *value*
 * differs from what this component itself last emitted (not by reference), so a PUT
 * response that echoes back deep-equal-but-new data doesn't clobber an in-progress row.
 */
export function KeyValueListField({
  label,
  keyPlaceholder = "key",
  valuePlaceholder = "value",
  items,
  onChange,
  errorFor,
  filterText,
}: KeyValueListFieldProps) {
  const lastEmitted = useRef(items);
  const [rows, setRows] = useState<Row[]>(() => rowsFrom(items));

  // Render-phase adjustment rather than an effect — an effect would paint one frame of
  // stale rows before catching up.
  if (!sameRecord(items, lastEmitted.current)) {
    lastEmitted.current = items;
    setRows(rowsFrom(items));
  }

  const errors = rowErrors(rows);
  const needle = filterText?.trim().toLowerCase() ?? "";
  const visibleRows = needle
    ? rows.filter(
        (r) => r.key.toLowerCase().includes(needle) || r.value.toLowerCase().includes(needle),
      )
    : rows;

  function emit(nextRows: Row[]) {
    if (rowErrors(nextRows).size > 0) return; // never emit a transiently-invalid set
    const record = recordFrom(nextRows);
    if (sameRecord(record, lastEmitted.current)) return;
    lastEmitted.current = record;
    onChange(record);
  }

  function updateField(rowId: string, field: "key" | "value", value: string) {
    setRows((rs) => rs.map((r) => (r.rowId === rowId ? { ...r, [field]: value } : r)));
  }

  function removeRow(rowId: string) {
    const next = rows.filter((r) => r.rowId !== rowId);
    setRows(next);
    emit(next);
  }

  function addRow() {
    setRows((rs) => [...rs, { rowId: newRowId(), key: "", value: "" }]);
  }

  return (
    <div className="text-sm">
      <span className="mb-1 block text-ink-muted">{label}</span>
      <div className="space-y-1.5">
        {needle && visibleRows.length === 0 && (
          <p className="text-xs text-ink-muted">No matches.</p>
        )}
        {visibleRows.map((row) => {
          const err = errors.get(row.rowId) ?? errorFor?.(row.key.trim()) ?? null;
          return (
            <div key={row.rowId}>
              <div className="flex items-center gap-1.5">
                <input
                  type="text"
                  value={row.key}
                  placeholder={keyPlaceholder}
                  onChange={(e) => updateField(row.rowId, "key", e.target.value)}
                  onBlur={() => emit(rows)}
                  className="field flex-1"
                />
                <span className="text-ink-muted">&rarr;</span>
                <input
                  type="text"
                  value={row.value}
                  placeholder={valuePlaceholder}
                  onChange={(e) => updateField(row.rowId, "value", e.target.value)}
                  onBlur={() => emit(rows)}
                  className="field flex-1"
                />
                <button
                  type="button"
                  onClick={() => removeRow(row.rowId)}
                  title="Remove"
                  aria-label={`Remove row${row.key ? ` ${row.key}` : ""}`}
                  className="rounded-full px-1.5 text-ink-muted hover:text-danger"
                >
                  ×
                </button>
              </div>
              {err && <p className="mt-0.5 text-xs text-danger">{err}</p>}
            </div>
          );
        })}
        <button
          type="button"
          onClick={addRow}
          className="rounded-md border border-dashed border-line px-2 py-1 text-xs text-ink-muted hover:border-accent hover:text-accent"
        >
          Add row
        </button>
      </div>
    </div>
  );
}
