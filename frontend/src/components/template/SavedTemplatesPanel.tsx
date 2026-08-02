import { useState } from "react";
import { useTemplateState } from "../../state/templateState";

/**
 * Format a byte count for the library list (e.g. 1.2 MB).
 */
function formatBytes(n: number | null | undefined): string {
  if (n == null) return "—";
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / (1024 * 1024)).toFixed(1)} MB`;
}

/**
 * Format an ISO timestamp for display, or an em dash when missing.
 */
function formatWhen(iso: string | null | undefined): string {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleString();
  } catch {
    return iso;
  }
}

/**
 * Named template library: activate, rename, or delete saved snapshots.
 */
export function SavedTemplatesPanel() {
  const {
    library,
    libraryBusy,
    uploading,
    calibrateAlso,
    setCalibrateAlso,
    activateLibraryEntry,
    renameLibraryEntry,
    deleteLibraryEntry,
    error,
  } = useTemplateState();
  const [renamingId, setRenamingId] = useState<string | null>(null);
  const [renameDraft, setRenameDraft] = useState("");

  const busy = libraryBusy || uploading;

  return (
    <section className="rounded-xl border border-line bg-panel p-5 shadow-sm">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="font-display text-xl font-semibold">Saved templates</h2>
          <p className="mt-1 text-sm text-ink-muted">
            Switch among named snapshots without re-uploading. Activate copies the
            saved baseline and tagged template into the live slot.
          </p>
        </div>
        <label className="flex items-center gap-2 text-xs text-ink-muted">
          <input
            type="checkbox"
            checked={calibrateAlso}
            disabled={busy}
            onChange={(e) => setCalibrateAlso(e.target.checked)}
          />
          Calibrate on activate
        </label>
      </div>

      {library.length === 0 ? (
        <p className="mt-4 text-sm text-ink-muted">
          No saved templates yet. Install one below — it will appear here under the
          label you choose.
        </p>
      ) : (
        <ul className="mt-4 divide-y divide-line/80 rounded-lg border border-line">
          {library.map((entry) => (
            <li
              key={entry.id}
              className="flex flex-wrap items-center justify-between gap-3 px-3 py-3 text-sm"
            >
              <div className="min-w-0 flex-1">
                {renamingId === entry.id ? (
                  <form
                    className="flex flex-wrap items-center gap-2"
                    onSubmit={(e) => {
                      e.preventDefault();
                      const next = renameDraft.trim();
                      if (!next) return;
                      void renameLibraryEntry(entry.id, next).then(() => {
                        setRenamingId(null);
                      });
                    }}
                  >
                    <input
                      type="text"
                      value={renameDraft}
                      maxLength={80}
                      disabled={busy}
                      onChange={(e) => setRenameDraft(e.target.value)}
                      className="min-w-[12rem] flex-1 rounded-md border border-line bg-paper px-2 py-1 text-ink"
                      aria-label="New template label"
                    />
                    <button
                      type="submit"
                      disabled={busy || !renameDraft.trim()}
                      className="rounded-md border border-line px-2 py-1 text-xs font-medium hover:border-accent hover:text-accent disabled:opacity-50"
                    >
                      Save
                    </button>
                    <button
                      type="button"
                      disabled={busy}
                      onClick={() => setRenamingId(null)}
                      className="rounded-md border border-line px-2 py-1 text-xs font-medium disabled:opacity-50"
                    >
                      Cancel
                    </button>
                  </form>
                ) : (
                  <>
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="font-medium text-ink">{entry.label}</span>
                      {entry.is_active ? (
                        <span className="rounded bg-accent-soft px-1.5 py-0.5 text-xs font-medium text-accent">
                          Active
                        </span>
                      ) : null}
                      {entry.has_profile ? (
                        <span className="text-xs text-ink-muted">profile</span>
                      ) : (
                        <span className="text-xs text-ink-muted">legacy</span>
                      )}
                    </div>
                    <p className="mt-0.5 text-xs text-ink-muted">
                      {formatBytes(entry.size_bytes)} · {formatWhen(entry.created_at)}
                      {entry.source_filename
                        ? ` · ${entry.source_filename}`
                        : null}
                    </p>
                  </>
                )}
              </div>
              {renamingId === entry.id ? null : (
                <div className="flex flex-wrap gap-2">
                  <button
                    type="button"
                    disabled={busy || entry.is_active}
                    onClick={() => void activateLibraryEntry(entry.id)}
                    className="rounded-md border border-line px-2.5 py-1 text-xs font-medium text-ink hover:border-accent hover:text-accent disabled:opacity-50"
                  >
                    {entry.is_active ? "Active" : "Activate"}
                  </button>
                  <button
                    type="button"
                    disabled={busy}
                    onClick={() => {
                      setRenamingId(entry.id);
                      setRenameDraft(entry.label);
                    }}
                    className="rounded-md border border-line px-2.5 py-1 text-xs font-medium text-ink hover:border-accent hover:text-accent disabled:opacity-50"
                  >
                    Rename
                  </button>
                  <button
                    type="button"
                    disabled={busy || entry.is_active}
                    onClick={() => {
                      if (
                        window.confirm(
                          `Delete saved template “${entry.label}”? This cannot be undone.`,
                        )
                      ) {
                        void deleteLibraryEntry(entry.id);
                      }
                    }}
                    className="rounded-md border border-line px-2.5 py-1 text-xs font-medium text-danger hover:border-danger disabled:opacity-50"
                  >
                    Delete
                  </button>
                </div>
              )}
            </li>
          ))}
        </ul>
      )}

      {error ? (
        <p className="mt-3 rounded-md bg-danger-soft px-3 py-2 text-sm text-danger">
          {error.split("\n")[0]}
        </p>
      ) : null}
    </section>
  );
}
