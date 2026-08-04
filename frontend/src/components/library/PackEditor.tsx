import { useEffect, useState } from "react";
import { type LibraryPackDraft, fetchLibraryPack } from "../../api";
import { useLibraryState } from "../../state/libraryState";
import { KeyValueListField } from "../KeyValueListField";

type VerbFamilyRow = {
  /** Stable per-row key so React doesn't remount an input the user is mid-edit of
   * when an earlier row's family name changes to match this one's (a real
   * possibility, since two rows editing toward the same family is legal until
   * save). */
  rowId: string;
  family: string;
  verbsText: string;
};

function rowsFromVerbFamilies(verbFamilies: Record<string, string[]>): VerbFamilyRow[] {
  return Object.entries(verbFamilies).map(([family, verbs], i) => ({
    rowId: `${family}-${i}`,
    family,
    verbsText: verbs.join(", "),
  }));
}

function verbFamiliesFromRows(rows: VerbFamilyRow[]): Record<string, string[]> {
  const out: Record<string, string[]> = {};
  for (const row of rows) {
    const family = row.family.trim();
    if (!family) continue;
    const verbs = row.verbsText
      .split(/[,\n]/)
      .map((v) => v.trim().toLowerCase())
      .filter(Boolean);
    if (verbs.length) out[family] = [...(out[family] ?? []), ...verbs];
  }
  return out;
}

/**
 * Create or edit a user-authored pack. `packId === null` is create mode — the id is
 * derived server-side from the label. Editing a built-in pack is not offered; the
 * Settings page never renders this for one.
 */
export function PackEditor({
  packId,
  onClose,
}: {
  packId: string | null;
  onClose: () => void;
}) {
  const { savePack } = useLibraryState();

  const [loading, setLoading] = useState(packId !== null);
  const [label, setLabel] = useState("");
  const [description, setDescription] = useState("");
  const [tagAliases, setTagAliases] = useState<Record<string, string>>({});
  const [verbRows, setVerbRows] = useState<VerbFamilyRow[]>([]);
  const [force, setForce] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (packId === null) return;
    let cancelled = false;
    setLoading(true);
    fetchLibraryPack(packId)
      .then((pack) => {
        if (cancelled) return;
        setLabel(pack.label);
        setDescription(pack.description);
        setTagAliases(pack.tag_aliases);
        setVerbRows(rowsFromVerbFamilies(pack.verb_families));
      })
      .catch((err) => {
        if (!cancelled) setError(err instanceof Error ? err.message : String(err));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [packId]);

  function addVerbRow() {
    setVerbRows((rows) => [
      ...rows,
      { rowId: `new-${rows.length}-${Date.now()}`, family: "", verbsText: "" },
    ]);
  }

  function updateVerbRow(rowId: string, patch: Partial<VerbFamilyRow>) {
    setVerbRows((rows) => rows.map((r) => (r.rowId === rowId ? { ...r, ...patch } : r)));
  }

  function removeVerbRow(rowId: string) {
    setVerbRows((rows) => rows.filter((r) => r.rowId !== rowId));
  }

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!label.trim()) {
      setError("Label is required.");
      return;
    }
    setSaving(true);
    setError(null);
    const draft: LibraryPackDraft = {
      label: label.trim(),
      description: description.trim(),
      tag_aliases: tagAliases,
      verb_families: verbFamiliesFromRows(verbRows),
      force,
    };
    try {
      await savePack(packId, draft);
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSaving(false);
    }
  }

  return (
    <form
      onSubmit={onSubmit}
      className="mt-4 space-y-4 rounded-lg border border-line bg-paper/40 p-4"
    >
      <div className="flex items-center justify-between gap-3">
        <h3 className="font-display text-lg font-semibold">
          {packId === null ? "New pack" : `Edit ${label || packId}`}
        </h3>
        <button
          type="button"
          onClick={onClose}
          className="text-xs text-ink-muted underline-offset-2 hover:text-accent hover:underline"
        >
          Cancel
        </button>
      </div>

      {loading ? (
        <p className="text-sm text-ink-muted">Loading pack…</p>
      ) : (
        <>
          <div className="grid gap-4 sm:grid-cols-2">
            <label className="block text-sm">
              <span className="mb-1 block text-ink-muted">Label</span>
              <input
                type="text"
                value={label}
                onChange={(e) => setLabel(e.target.value)}
                placeholder="e.g. Nursing"
                className="field"
                required
              />
            </label>
            <label className="block text-sm">
              <span className="mb-1 block text-ink-muted">Description (optional)</span>
              <input
                type="text"
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                placeholder="e.g. Clinical vocabulary and care-delivery verbs."
                className="field"
              />
            </label>
          </div>

          <KeyValueListField
            label="Tag aliases (spelling seen in a posting → your canonical tag)"
            keyPlaceholder="e.g. bls"
            valuePlaceholder="e.g. basic life support"
            items={tagAliases}
            onChange={setTagAliases}
          />

          <div className="text-sm">
            <span className="mb-1 block text-ink-muted">
              Verb families (near-synonym opening verbs, grouped by the claim they make)
            </span>
            <div className="space-y-2">
              {verbRows.map((row) => (
                <div key={row.rowId} className="flex items-start gap-1.5">
                  <input
                    type="text"
                    value={row.family}
                    onChange={(e) => updateVerbRow(row.rowId, { family: e.target.value })}
                    placeholder="family, e.g. care"
                    className="field w-32 flex-none"
                  />
                  <input
                    type="text"
                    value={row.verbsText}
                    onChange={(e) => updateVerbRow(row.rowId, { verbsText: e.target.value })}
                    placeholder="verbs, comma-separated — e.g. administered, assessed, charted"
                    className="field flex-1"
                  />
                  <button
                    type="button"
                    onClick={() => removeVerbRow(row.rowId)}
                    title="Remove family"
                    className="mt-2 rounded-full px-1.5 text-ink-muted hover:text-danger"
                  >
                    ×
                  </button>
                </div>
              ))}
              <button
                type="button"
                onClick={addVerbRow}
                className="rounded-md border border-line px-2 py-1 text-xs text-ink-muted hover:border-accent hover:text-accent"
              >
                Add family
              </button>
            </div>
          </div>

          <label className="flex cursor-pointer items-start gap-2 text-xs text-ink-muted">
            <input
              type="checkbox"
              checked={force}
              onChange={(e) => setForce(e.target.checked)}
              className="mt-0.5 accent-[var(--color-accent)]"
            />
            <span>
              Overwrite a target another enabled pack already claims for the same alias,
              instead of failing with a conflict.
            </span>
          </label>

          {error && (
            <p className="whitespace-pre-line rounded-md bg-danger-soft px-3 py-2 text-xs text-danger">
              {error}
            </p>
          )}

          <div className="flex items-center gap-3">
            <button
              type="submit"
              disabled={saving}
              className="rounded-md bg-accent px-4 py-1.5 text-sm font-medium text-white hover:bg-accent/90 disabled:opacity-50"
            >
              {saving ? "Saving…" : "Save pack"}
            </button>
          </div>
        </>
      )}
    </form>
  );
}
