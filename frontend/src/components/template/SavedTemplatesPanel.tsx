import { useState } from "react";
import { Button, Tile } from "../ui";
import {
  GalleryActions,
  GalleryCard,
  GalleryRow,
  TemplateThumb,
  selectButtonClass,
} from "./TemplateGallery";
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
        <GalleryRow>
          {library.map((entry) => (
            <GalleryCard key={entry.id} active={entry.is_active}>
              <TemplateThumb
                src={`/api/template/library/${encodeURIComponent(entry.id)}/thumb.png?v=${encodeURIComponent(entry.created_at)}`}
                alt={`First page of ${entry.label}`}
                label={entry.label}
              />
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
                    <Button type="submit" size="sm" disabled={busy || !renameDraft.trim()}>
                      Save
                    </Button>
                    <Button size="sm" disabled={busy} onClick={() => setRenamingId(null)}>
                      Cancel
                    </Button>
                  </form>
                ) : (
                  <div>
                    <span className="font-medium text-ink">{entry.label}</span>
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
                  <GalleryActions>
                    <button
                      type="button"
                      disabled={busy || entry.is_active}
                      onClick={() => void activateLibraryEntry(entry.id)}
                      className={selectButtonClass(entry.is_active)}
                    >
                      {entry.is_active ? "In use" : "Use"}
                    </button>
                    <Button
                      size="sm"
                      disabled={busy}
                      onClick={() => {
                        setRenamingId(entry.id);
                        setRenameDraft(entry.label);
                      }}
                    >
                      Rename
                    </Button>
                    <Button
                      variant="danger"
                      size="sm"
                      disabled={busy || entry.is_active}
                      onClick={() => void handleDelete(entry.id, entry.label)}
                    >
                      Delete
                    </Button>
                  </GalleryActions>
                )}
              </div>
            </GalleryCard>
          ))}
        </GalleryRow>
      )}

      {error ? (
        <p className="mt-3 rounded-sm bg-danger-soft px-3 py-2 text-sm text-danger">
          {error.split("\n")[0]}
        </p>
      ) : null}
    </Tile>
  );
}
