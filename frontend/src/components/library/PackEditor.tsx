import { useEffect, useMemo, useState } from "react";
import { type LibraryPackDraft, fetchLibraryPack } from "../../api";
import { errorsFor, validatePackDraft } from "../../lib/packValidation";
import { Modal } from "../Modal";
import { KeyValueListField } from "../KeyValueListField";
import { VerbFamilyCard } from "./VerbFamilyEditor";
import { useLibraryState } from "../../state/libraryState";

type VerbFamilyRow = {
  /** Stable per-row key so React doesn't remount an input the user is mid-edit of
   * when an earlier row's family name changes to match this one's (a real
   * possibility, since two rows editing toward the same family is legal until
   * save). */
  rowId: string;
  family: string;
  verbs: string[];
};

function rowsFromVerbFamilies(verbFamilies: Record<string, string[]>): VerbFamilyRow[] {
  return Object.entries(verbFamilies).map(([family, verbs], i) => ({
    rowId: `${family}-${i}`,
    family,
    verbs,
  }));
}

function verbFamiliesFromRows(rows: VerbFamilyRow[]): Record<string, string[]> {
  const out: Record<string, string[]> = {};
  for (const row of rows) {
    const family = row.family.trim();
    // A fully blank row (no name, no verbs) is an inert placeholder from "Add family" —
    // drop it silently. A *named* family with zero verbs is kept (even as an empty
    // array) so `validatePackDraft` can see and flag it, rather than losing it here.
    if (!family) continue;
    out[family] = [...(out[family] ?? []), ...row.verbs];
  }
  return out;
}

/** Matches the exact wording `write_pack` appends when a `force=true` retry would
 * resolve the conflict (libraries.py:738-742) — narrow coupling to our own backend,
 * kept as a named constant so a wording change there is easy to find here too. */
const FORCE_HINT_SUFFIX = "pass force=true to override it.";

/**
 * Create or edit a vocabulary pack, in a wide modal. `packId === null` is create mode —
 * the id is derived server-side from the label. Shipped packs edit via a shadow file.
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
  const [filter, setFilter] = useState("");
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
      { rowId: `new-${rows.length}-${Date.now()}`, family: "", verbs: [] },
    ]);
  }

  function updateVerbRow(rowId: string, patch: Partial<VerbFamilyRow>) {
    setVerbRows((rows) => rows.map((r) => (r.rowId === rowId ? { ...r, ...patch } : r)));
  }

  function removeVerbRow(rowId: string) {
    setVerbRows((rows) => rows.filter((r) => r.rowId !== rowId));
  }

  const validationErrors = useMemo(
    () =>
      validatePackDraft({
        label,
        tag_aliases: tagAliases,
        verb_families: verbFamiliesFromRows(verbRows),
      }),
    [label, tagAliases, verbRows],
  );

  const needle = filter.trim().toLowerCase();
  const aliasCount = Object.keys(tagAliases).length;
  const verbCount = verbRows.reduce((n, r) => n + r.verbs.length, 0);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (validationErrors.length > 0) return;
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

  const canForce = error?.includes(FORCE_HINT_SUFFIX) ?? false;

  return (
    <Modal title={packId === null ? "New pack" : `Edit ${label || packId}`} onClose={onClose} wide>
      {loading ? (
        <p className="mt-4 text-sm text-ink-muted">Loading pack…</p>
      ) : (
        <form onSubmit={onSubmit} className="mt-4 space-y-4">
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
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
              {errorsFor(validationErrors, { kind: "label" }).map((m) => (
                <span key={m} className="mt-1 block text-xs text-danger">
                  {m}
                </span>
              ))}
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

          <p className="text-xs text-ink-muted">
            {aliasCount} alias{aliasCount === 1 ? "" : "es"} &middot; {verbCount} verb
            {verbCount === 1 ? "" : "s"} in {verbRows.length} famil
            {verbRows.length === 1 ? "y" : "ies"}
          </p>

          <label className="block text-sm">
            <span className="mb-1 block text-ink-muted">Filter aliases and verbs</span>
            <input
              type="search"
              value={filter}
              onChange={(e) => setFilter(e.target.value)}
              placeholder="Type to narrow the lists below…"
              className="field"
            />
          </label>

          <div className="max-h-64 overflow-y-auto pr-1">
            <KeyValueListField
              label={`Tag aliases (${aliasCount}) — spelling seen in a posting → your canonical tag`}
              keyPlaceholder="e.g. bls"
              valuePlaceholder="e.g. basic life support"
              items={tagAliases}
              onChange={setTagAliases}
              errorFor={(key) => errorsFor(validationErrors, { kind: "alias", key })[0]}
              filterText={needle}
            />
          </div>

          <div className="text-sm">
            <span className="mb-1 block text-ink-muted">
              Verb families ({verbRows.length}) — near-synonym opening verbs, grouped by
              the claim they make
            </span>
            <div className="space-y-2">
              {verbRows.map((row) => {
                if (
                  needle &&
                  !row.family.toLowerCase().includes(needle) &&
                  !row.verbs.some((v) => v.toLowerCase().includes(needle))
                ) {
                  return null;
                }
                const cardErrors = [
                  ...errorsFor(validationErrors, { kind: "family", family: row.family }),
                  ...row.verbs.flatMap((v) =>
                    errorsFor(validationErrors, { kind: "verb", family: row.family, verb: v }),
                  ),
                ];
                return (
                  <VerbFamilyCard
                    key={row.rowId}
                    family={row.family}
                    verbs={row.verbs}
                    onFamilyChange={(family) => updateVerbRow(row.rowId, { family })}
                    onVerbsChange={(verbs) => updateVerbRow(row.rowId, { verbs })}
                    onRemove={() => removeVerbRow(row.rowId)}
                    error={cardErrors[0] ?? null}
                  />
                );
              })}
              <button
                type="button"
                onClick={addVerbRow}
                className="rounded-md border border-dashed border-line px-2 py-1 text-xs text-ink-muted hover:border-accent hover:text-accent"
              >
                + Add family
              </button>
            </div>
          </div>

          {canForce && (
            <label className="flex cursor-pointer items-start gap-2 text-xs text-ink-muted">
              <input
                type="checkbox"
                checked={force}
                onChange={(e) => setForce(e.target.checked)}
                className="mt-0.5 accent-[var(--color-accent)]"
              />
              <span>
                Overwrite the conflicting target and save anyway.
              </span>
            </label>
          )}

          {error && (
            <p className="whitespace-pre-line rounded-md bg-danger-soft px-3 py-2 text-xs text-danger">
              {error}
            </p>
          )}

          <div className="flex items-center gap-3">
            <button
              type="button"
              onClick={onClose}
              className="rounded-md border border-line px-3 py-1.5 text-sm font-medium text-ink hover:border-accent hover:text-accent"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={saving || validationErrors.length > 0}
              className="rounded-md bg-accent px-4 py-1.5 text-sm font-medium text-on-accent hover:bg-accent/90 disabled:opacity-50"
            >
              {saving ? "Saving…" : canForce ? "Overwrite and save" : "Save pack"}
            </button>
            {!saving && validationErrors.length > 0 && (
              <span className="text-xs text-ink-muted">
                Fix {validationErrors.length} issue{validationErrors.length === 1 ? "" : "s"} to save.
              </span>
            )}
          </div>
        </form>
      )}
    </Modal>
  );
}
