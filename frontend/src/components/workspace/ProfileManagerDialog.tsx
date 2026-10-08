import { type FormEvent, useState } from "react";
import { Modal } from "../Modal";
import { useConfirm } from "../../state/confirmState";
import { useWorkspaceState } from "../../state/workspaceState";

/**
 * Modal: create, duplicate, rename, and delete profiles.
 *
 * Mirrors the affordances of `SavedTemplatesPanel` (activate / rename / delete rows
 * with inline rename forms and a confirm delete guard) so the two lists of
 * saved things in this app feel the same.
 */
export function ProfileManagerDialog({
  onClose,
  onActivate,
}: {
  onClose: () => void;
  onActivate: (id: string) => Promise<void>;
}) {
  const { workspaces, activeId, switching, create, rename, remove } = useWorkspaceState();
  const { confirm } = useConfirm();
  const [newLabel, setNewLabel] = useState("");
  const [duplicate, setDuplicate] = useState(true);
  const [busy, setBusy] = useState(false);
  const [localError, setLocalError] = useState<string | null>(null);
  const [renamingId, setRenamingId] = useState<string | null>(null);
  const [renameDraft, setRenameDraft] = useState("");

  const disabled = busy || switching;

  async function handleCreate(e: FormEvent) {
    e.preventDefault();
    const label = newLabel.trim();
    if (!label) return;
    setBusy(true);
    setLocalError(null);
    try {
      await create(label, duplicate ? activeId : null);
      setNewLabel("");
    } catch (err) {
      setLocalError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  async function handleActivate(id: string) {
    if (id === activeId) return;
    setBusy(true);
    setLocalError(null);
    try {
      await onActivate(id);
    } catch (err) {
      setLocalError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  async function handleRename(id: string) {
    const label = renameDraft.trim();
    if (!label) return;
    setBusy(true);
    setLocalError(null);
    try {
      await rename(id, label);
      setRenamingId(null);
    } catch (err) {
      setLocalError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  async function handleDelete(id: string, label: string) {
    const ok = await confirm({
      title: "Delete profile",
      message: `Delete profile “${label}”? This removes its resume, template, and settings and cannot be undone.`,
      confirmLabel: "Delete",
      tone: "danger",
    });
    if (!ok) return;
    setBusy(true);
    setLocalError(null);
    try {
      await remove(id);
    } catch (err) {
      setLocalError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal title="Profiles" onClose={onClose}>
      <p className="mt-1 text-sm text-ink-muted">
        Each profile has its own master resume, template, and settings — switching swaps all of it
        at once.
      </p>

      <ul className="mt-4 max-h-64 divide-y divide-line/80 overflow-y-auto rounded-sm border border-line">
        {workspaces.map((w) => (
          <li
            key={w.id}
            className="flex flex-wrap items-center justify-between gap-2 px-3 py-2 text-sm"
          >
            {renamingId === w.id ? (
              <form
                className="flex flex-1 flex-wrap items-center gap-2"
                onSubmit={(e) => {
                  e.preventDefault();
                  void handleRename(w.id);
                }}
              >
                <input
                  type="text"
                  value={renameDraft}
                  maxLength={80}
                  disabled={disabled}
                  onChange={(e) => setRenameDraft(e.target.value)}
                  className="min-w-[10rem] flex-1 rounded-sm border border-line-hover bg-field px-2 py-1 text-ink"
                  aria-label="New profile name"
                  autoFocus
                />
                <button
                  type="submit"
                  disabled={disabled || !renameDraft.trim()}
                  className="rounded-sm border border-line-hover px-2 py-1 text-xs font-medium hover:border-ink disabled:opacity-50"
                >
                  Save
                </button>
                <button
                  type="button"
                  disabled={disabled}
                  onClick={() => setRenamingId(null)}
                  className="rounded-sm border border-line-hover px-2 py-1 text-xs font-medium disabled:opacity-50"
                >
                  Cancel
                </button>
              </form>
            ) : (
              <>
                <div className="flex items-center gap-2">
                  <span className="font-medium text-ink">{w.label}</span>
                  {w.id === activeId ? (
                    <span className="rounded-sm bg-accent-soft px-1.5 py-0.5 text-xs font-medium text-accent">
                      Active
                    </span>
                  ) : null}
                </div>
                <div className="flex flex-wrap gap-2">
                  <button
                    type="button"
                    disabled={disabled || w.id === activeId}
                    onClick={() => void handleActivate(w.id)}
                    className="rounded-sm border border-line-hover px-2.5 py-1 text-xs font-medium text-ink hover:border-ink disabled:opacity-50"
                  >
                    {w.id === activeId ? "Active" : "Switch"}
                  </button>
                  <button
                    type="button"
                    disabled={disabled}
                    onClick={() => {
                      setRenamingId(w.id);
                      setRenameDraft(w.label);
                    }}
                    className="rounded-sm border border-line-hover px-2.5 py-1 text-xs font-medium text-ink hover:border-ink disabled:opacity-50"
                  >
                    Rename
                  </button>
                  <button
                    type="button"
                    disabled={disabled || w.id === activeId || workspaces.length <= 1}
                    onClick={() => void handleDelete(w.id, w.label)}
                    className="rounded-sm border border-danger/45 px-2.5 py-1 text-xs font-medium text-danger hover:border-danger disabled:opacity-50"
                  >
                    Delete
                  </button>
                </div>
              </>
            )}
          </li>
        ))}
      </ul>

      <form onSubmit={handleCreate} className="mt-4 space-y-2 border-t border-line/80 pt-4">
        <label className="block text-sm font-medium text-ink" htmlFor="new-profile-label">
          New profile
        </label>
        <div className="flex flex-wrap gap-2">
          <input
            id="new-profile-label"
            type="text"
            value={newLabel}
            maxLength={80}
            disabled={disabled}
            onChange={(e) => setNewLabel(e.target.value)}
            placeholder="e.g. Data Science"
            className="min-w-[12rem] flex-1 rounded-sm border border-line-hover bg-field px-2 py-1.5 text-ink"
          />
          <button
            type="submit"
            disabled={disabled || !newLabel.trim()}
            className="rounded-sm bg-primary px-3 py-1.5 text-[13px] font-medium text-on-primary hover:bg-primary/85 disabled:opacity-50"
          >
            Create
          </button>
        </div>
        <label className="flex items-center gap-2 text-xs text-ink-muted">
          <input
            type="checkbox"
            checked={duplicate}
            disabled={disabled}
            onChange={(e) => setDuplicate(e.target.checked)}
          />
          Start as a copy of the current profile (resume, template, settings)
        </label>
      </form>

      {localError ? (
        <p className="mt-3 rounded-sm bg-danger-soft px-3 py-2 text-sm text-danger">
          {localError.split("\n")[0]}
        </p>
      ) : null}
    </Modal>
  );
}
