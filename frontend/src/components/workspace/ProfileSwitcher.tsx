import { useState } from "react";
import { useEditorState } from "../../state/editorState";
import { useWorkspaceState } from "../../state/workspaceState";
import { ProfileManagerDialog } from "./ProfileManagerDialog";

/**
 * Header control: switch the active profile, or open the manager to create,
 * duplicate, rename, or delete one.
 *
 * Reads `useEditorState()` to warn about unsaved master-resume edits before
 * switching. This works because `ProfileSwitcher` renders inside the keyed
 * Run/Editor/Template scope (see App.tsx) — at the moment a switch is requested it
 * is still the *old* profile's editor state, which is exactly what needs checking.
 */
export function ProfileSwitcher() {
  const { workspaces, activeId, switching, error, activate } = useWorkspaceState();
  const { dirty } = useEditorState();
  const [managerOpen, setManagerOpen] = useState(false);

  function handleSwitch(id: string) {
    if (!id || id === activeId) return;
    if (dirty) {
      const ok = window.confirm(
        "You have unsaved master-resume edits. Switching profiles discards them. Continue?",
      );
      if (!ok) return;
    }
    void activate(id);
  }

  return (
    <div className="flex items-center gap-2">
      <label className="flex items-center gap-2 text-sm">
        <span className="text-ink-muted">Profile</span>
        <select
          value={activeId ?? ""}
          disabled={switching || workspaces.length === 0}
          onChange={(e) => handleSwitch(e.target.value)}
          className="rounded-md border border-line bg-paper px-2 py-1.5 text-ink disabled:opacity-50"
          aria-label="Active profile"
        >
          {workspaces.length === 0 ? <option value="">—</option> : null}
          {workspaces.map((w) => (
            <option key={w.id} value={w.id}>
              {w.label}
            </option>
          ))}
        </select>
      </label>
      <button
        type="button"
        onClick={() => setManagerOpen(true)}
        disabled={switching}
        className="rounded-md border border-line px-2.5 py-1.5 text-xs font-medium text-ink-muted hover:border-accent hover:text-accent disabled:opacity-50"
      >
        Manage
      </button>
      {switching ? <span className="text-xs text-ink-muted">Switching…</span> : null}
      {error ? <span className="text-xs text-danger">{error.split("\n")[0]}</span> : null}
      {managerOpen ? <ProfileManagerDialog onClose={() => setManagerOpen(false)} /> : null}
    </div>
  );
}
