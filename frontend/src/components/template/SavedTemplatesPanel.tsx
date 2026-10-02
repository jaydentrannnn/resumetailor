import { useState } from "react";
import { useConfirm } from "../../state/confirmState";
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
    activateLibraryEntry,
    renameLibraryEntry,
    deleteLibraryEntry,
    error,
  } = useTemplateState();
  const { confirm } = useConfirm();
  const [renamingId, setRenamingId] = useState<string | null>(null);
  const [renameDraft, setRenameDraft] = useState("");

  const busy = libraryBusy || uploading;

  async function handleDelete(id: string, label: string) {
    const ok = await confirm({
      title: "Delete template",
      message: `Delete saved template “${label}”? This cannot be undone.`,
      confirmLabel: "Delete",
      tone: "danger",
    });
    if (!ok) return;
    void deleteLibraryEntry(id);
  }

  return (
    <section className="rounded-xl border border-line bg-panel p-5 shadow-sm">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="font-display text-xl font-semibold">Your templates</h2>
          <p className="mt-1 text-sm text-ink-muted">
            Every template you've installed (up to 20). Switch between them without re-uploading;
            your resume content stays the same.
          </p>
        </div>
      </div>

      {library.length === 0 ? (
        <p className="mt-4 text-sm text-ink-muted">
          No saved templates yet. Install one below — it will appear here under the label you
          choose.
        </p>
      ) : (
        <ul className="mt-4 grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {library.map((entry) => (
            <li
              key={entry.id}
              className={`flex flex-col overflow-hidden rounded-lg border bg-paper/40 text-sm ${
                entry.is_active ? "border-accent ring-1 ring-accent" : "border-line"
              }`}
            >
              <Thumbnail id={entry.id} version={entry.created_at} label={entry.label} />
              <div className="flex flex-1 flex-col gap-2 border-t border-line p-3">
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
                      className="min-w-0 flex-1 rounded-md border border-line bg-paper px-2 py-1 text-ink"
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
                  <div>
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="font-medium text-ink">{entry.label}</span>
                      {entry.is_active ? (
                        <span className="rounded bg-accent-soft px-1.5 py-0.5 text-xs font-medium text-accent">
                          In use
                        </span>
                      ) : null}
                    </div>
                    <p
                      className="mt-0.5 truncate text-xs text-ink-muted"
                      title={entry.source_filename ?? undefined}
                    >
                      {formatWhen(entry.created_at)}
                      {entry.source_filename ? ` · ${entry.source_filename}` : null} ·{" "}
                      {formatBytes(entry.size_bytes)}
                    </p>
                  </div>
                )}
                {renamingId === entry.id ? null : (
                  <div className="mt-auto flex flex-wrap gap-2">
                    <button
                      type="button"
                      disabled={busy || entry.is_active}
                      onClick={() => void activateLibraryEntry(entry.id)}
                      className="rounded-md border border-line px-2.5 py-1 text-xs font-medium text-ink hover:border-accent hover:text-accent disabled:opacity-50"
                    >
                      {entry.is_active ? "In use" : "Use"}
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
                      onClick={() => void handleDelete(entry.id, entry.label)}
                      className="rounded-md border border-line px-2.5 py-1 text-xs font-medium text-danger hover:border-danger disabled:opacity-50"
                    >
                      Delete
                    </button>
                  </div>
                )}
              </div>
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

/** First page of the template's original document; a plain card when it can't render. */
function Thumbnail({ id, version, label }: { id: string; version: string; label: string }) {
  const [failed, setFailed] = useState(false);
  return (
    <div className="flex aspect-[8.5/11] max-h-72 items-start justify-center overflow-hidden bg-white">
      {failed ? (
        <span className="m-auto px-4 text-center text-xs text-ink-muted">
          Preview unavailable (needs Word or LibreOffice)
        </span>
      ) : (
        <img
          src={`/api/template/library/${encodeURIComponent(id)}/thumb.png?v=${encodeURIComponent(version)}`}
          alt={`First page of ${label}`}
          loading="lazy"
          className="w-full object-cover object-top"
          onError={() => setFailed(true)}
        />
      )}
    </div>
  );
}
