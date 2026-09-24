import { useState } from "react";
import { createPortal } from "react-dom";
import { useConfirm } from "../../state/confirmState";
import { useEditorState } from "../../state/editorState";
import { useWorkspaceState } from "../../state/workspaceState";
import { useApplicantProfile } from "../../state/applicantProfileState";
import { useRunState } from "../../state/runState";
import { useLibraryState } from "../../state/libraryState";
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
/** `stacked` lays the control out for the header settings menu. */
export function ProfileSwitcher({ stacked = false }: { stacked?: boolean }) {
  const { workspaces, activeId, switching, error, activate } = useWorkspaceState();
  const { dirty } = useEditorState();
  const applicant = useApplicantProfile();
  const { flushSettings, discardSettings, settingsSaveState } = useRunState();
  const { flushOverrides, discardOverrides, overridesSaveState } = useLibraryState();
  const { confirm, choice } = useConfirm();
  const [managerOpen, setManagerOpen] = useState(false);

  async function handleSwitch(id: string) {
    if (!id || id === activeId) return;
    if (dirty || applicant.dirty || applicant.saving) {
      const ok = await confirm({
        title: "Unsaved edits",
        message:
          "You have unsaved resume or application-profile edits. Switching profiles discards them. Continue?",
        confirmLabel: "Switch anyway",
        tone: "danger",
      });
      if (!ok) return;
    }
    if (settingsSaveState !== "saved") {
      let saved = await flushSettings();
      while (!saved) {
        const decision = await choice({
          title: "Tailor settings could not be saved",
          message:
            "Retry saving before switching profiles, stay here, or discard these settings changes.",
          options: [
            { id: "retry", label: "Retry save" },
            { id: "discard", label: "Discard changes", tone: "danger" },
          ],
          cancelLabel: "Stay",
        });
        if (decision === "retry") saved = await flushSettings();
        else if (decision === "discard") {
          await discardSettings();
          break;
        } else return;
      }
    }
    if (overridesSaveState !== "saved") {
      let saved = await flushOverrides();
      while (!saved) {
        const decision = await choice({
          title: "Vocabulary additions could not be saved",
          message:
            "Retry saving before switching profiles, stay here, or discard these vocabulary changes.",
          options: [
            { id: "retry", label: "Retry save" },
            { id: "discard", label: "Discard changes", tone: "danger" },
          ],
          cancelLabel: "Stay",
        });
        if (decision === "retry") saved = await flushOverrides();
        else if (decision === "discard") {
          await discardOverrides();
          break;
        } else return;
      }
    }
    try {
      await activate(id);
    } catch {
      /* workspace state displays the error */
    }
  }

  return (
    <div className={stacked ? "space-y-2" : "flex items-center gap-2"}>
      <label className={stacked ? "block space-y-1 text-sm" : "flex items-center gap-2 text-sm"}>
        <span className={stacked ? "block text-ink-muted" : "text-ink-muted"}>Active profile</span>
        <select
          value={activeId ?? ""}
          disabled={switching || applicant.saving || workspaces.length === 0}
          onChange={(e) => void handleSwitch(e.target.value)}
          className={`rounded-md border border-line bg-paper px-2 py-1.5 text-ink disabled:opacity-50 ${stacked ? "w-full" : ""}`}
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
        {stacked ? "Manage profiles…" : "Manage"}
      </button>
      {switching ? <span className="text-xs text-ink-muted">Switching…</span> : null}
      {error ? <span className="text-xs text-danger">{error.split("\n")[0]}</span> : null}
      {/* Portaled: a fixed overlay inside the blurred header would be laid out against
          the header box (backdrop-filter makes it the containing block), not the viewport. */}
      {managerOpen
        ? createPortal(
            <ProfileManagerDialog
              onClose={() => setManagerOpen(false)}
              onActivate={handleSwitch}
            />,
            document.body,
          )
        : null}
    </div>
  );
}
