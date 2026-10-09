import { type FormEvent, useState } from "react";
import { Modal } from "../Modal";
import { Button, StatusChip } from "../ui";
import { useConfirm } from "../../state/confirmState";
import { useWorkspaceState } from "../../state/workspaceState";

/**
 * Modal: create, duplicate, rename, and delete profiles.
 *
 * Rows follow the app's list standard (hairlines between rows, no box): the active
 * profile wears a status chip, Switch/Rename are plain housekeeping buttons and Delete
 * is the tinted danger level, like Remove on Settings → AI model.
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

      {/* One grid, rows on its subgrid, so Switch / Rename / Delete line up in columns
          even on the active row, which has a chip and no Delete. */}
      <ul className="mt-4 grid max-h-64 grid-cols-[minmax(0,1fr)_auto_auto_auto] divide-y divide-line overflow-y-auto">
        {workspaces.map((w) => (
          <li
            key={w.id}
            className="col-span-4 grid min-h-12 grid-cols-subgrid items-center gap-x-2 py-2 text-sm"
          >
            {renamingId === w.id ? (
              <form
                className="col-span-4 flex flex-wrap items-center gap-2"
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
                  className="field min-w-[10rem] flex-1"
                  aria-label="New profile name"
                  autoFocus
                />
                <Button
                  type="submit"
                  variant="plain"
                  size="sm"
                  disabled={disabled || !renameDraft.trim()}
                >
                  Save
                </Button>
                <Button
                  variant="ghost"
                  size="sm"
                  disabled={disabled}
                  onClick={() => setRenamingId(null)}
                >
                  Cancel
                </Button>
              </form>
            ) : (
              <>
                <span className="min-w-0 truncate font-medium text-ink">{w.label}</span>
                {w.id === activeId ? (
                  <StatusChip tone="done" className="justify-self-center">
                    Active
                  </StatusChip>
                ) : (
                  <Button
                    variant="plain"
                    size="sm"
                    disabled={disabled}
                    onClick={() => void handleActivate(w.id)}
                  >
                    Switch
                  </Button>
                )}
                <Button
                  variant="plain"
                  size="sm"
                  disabled={disabled}
                  onClick={() => {
                    setRenamingId(w.id);
                    setRenameDraft(w.label);
                  }}
                >
                  Rename
                </Button>
                {w.id === activeId ? (
                  <span />
                ) : (
                  <Button
                    variant="danger"
                    size="sm"
                    disabled={disabled}
                    onClick={() => void handleDelete(w.id, w.label)}
                  >
                    Delete
                  </Button>
                )}
              </>
            )}
          </li>
        ))}
      </ul>

      <form onSubmit={handleCreate} className="space-y-2 border-t border-line pt-4">
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
            className="field min-w-[12rem] flex-1"
          />
          <Button type="submit" variant="primary" disabled={disabled || !newLabel.trim()}>
            Create
          </Button>
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
