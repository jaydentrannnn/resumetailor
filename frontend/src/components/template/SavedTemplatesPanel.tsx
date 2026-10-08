import { Tile } from "../ui";
import { buttonClass } from "../../lib/buttonClass";
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
    <Tile>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="rt-tile-title">Your templates</h2>
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
        <ul className="mt-4 grid grid-cols-1 gap-3 sm:grid-cols-[repeat(auto-fill,minmax(180px,200px))]">
          {library.map((entry) => (
            <li
              key={entry.id}
              className={`flex flex-col overflow-hidden rounded-sm border bg-field text-sm ${
                entry.is_active ? "border-selected-line" : "border-line"
              }`}
            >
              <Thumbnail id={entry.id} version={entry.created_at} label={entry.label} />
              <div className="flex flex-1 flex-col gap-2 p-3">
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
                      className="min-w-0 flex-1 rounded-sm border border-line bg-paper px-2 py-1 text-ink"
                      aria-label="New template label"
                    />
                    <button
                      type="submit"
                      disabled={busy || !renameDraft.trim()}
                      className={buttonClass("secondary", "sm")}
                    >
                      Save
                    </button>
                    <button
                      type="button"
                      disabled={busy}
                      onClick={() => setRenamingId(null)}
                      className={buttonClass("secondary", "sm")}
                    >
                      Cancel
                    </button>
                  </form>
                ) : (
                  <div>
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="font-medium text-ink">{entry.label}</span>
                      {entry.is_active ? (
                        <span className="rounded-sm border border-selected-line bg-selected px-1.5 py-0.5 text-xs font-medium text-on-selected">
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
                      className={
                        entry.is_active
                          ? "rounded-sm border border-selected-line bg-selected px-3 py-1.5 text-xs font-medium text-on-selected"
                          : buttonClass("secondary", "sm")
                      }
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
                      className={buttonClass("secondary", "sm")}
                    >
                      Rename
                    </button>
                    <button
                      type="button"
                      disabled={busy || entry.is_active}
                      onClick={() => void handleDelete(entry.id, entry.label)}
                      className={buttonClass("danger", "sm")}
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
        <p className="mt-3 rounded-sm bg-danger-soft px-3 py-2 text-sm text-danger">
          {error.split("\n")[0]}
        </p>
      ) : null}
    </Tile>
  );
}

/** First page of the template's original document; a plain card when it can't render. */
function Thumbnail({ id, version, label }: { id: string; version: string; label: string }) {
  const [failed, setFailed] = useState(false);
  return (
    <div className="flex h-56 items-start justify-center overflow-hidden bg-doc-preview">
      {failed ? (
        <span className="m-auto px-4 text-center text-xs text-ink-muted">
          Preview unavailable (needs Word or LibreOffice)
        </span>
      ) : (
        <img
          src={`/api/template/library/${encodeURIComponent(id)}/thumb.png?v=${encodeURIComponent(version)}`}
          alt={`First page of ${label}`}
          loading="lazy"
          className="h-full w-full object-contain object-top"
          onError={() => setFailed(true)}
        />
      )}
    </div>
  );
}
