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
export function ProfileSwitcher() {
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

  const locked = switching || applicant.saving;
  return (
    <div className="space-y-2">
      {/* A list, not a <select>: the active profile is marked like the header nav (ink
          text, accent bar) instead of sitting in a box. */}
      <div role="group" aria-label="Active profile" className="-mx-2 space-y-px">
        {workspaces.length === 0 ? <p className="px-2 text-sm text-ink-muted">—</p> : null}
        {workspaces.map((w) => {
          const on = w.id === activeId;
          return (
            <button
              key={w.id}
              type="button"
              aria-current={on || undefined}
              title={on ? "Active profile" : `Switch to ${w.label}`}
              disabled={locked}
              onClick={() => void handleSwitch(w.id)}
              className={`rt-row-action relative block w-full truncate px-2.5 py-1 text-left text-[13px] transition-colors duration-[var(--dur-short)] before:absolute before:inset-y-1 before:left-0 before:w-0.5 disabled:opacity-50 ${
                on
                  ? "font-medium text-ink before:bg-accent"
                  : "text-ink-muted before:bg-transparent hover:text-ink"
              }`}
            >
              {w.label}
            </button>
          );
        })}
      </div>
      <button
        type="button"
        onClick={() => setManagerOpen(true)}
        disabled={switching}
        className="rt-link text-xs disabled:opacity-50"
      >
        Manage profiles…
      </button>
      {switching ? <span className="text-xs text-ink-muted">Switching…</span> : null}
      {error ? <span className="text-xs text-danger">{error.split("\n")[0]}</span> : null}
      {/* Portaled so the dialog's fixed overlay is laid out against the viewport, not the
          menu panel it is opened from. */}
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
