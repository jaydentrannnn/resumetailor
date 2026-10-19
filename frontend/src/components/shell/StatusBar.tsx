import { useEffect } from "react";
import { Link } from "react-router-dom";
import { useStatusLine } from "../../lib/toast";
import { useApplicantProfile } from "../../state/applicantProfileState";
import { useEditorState } from "../../state/editorState";
import { useRunState } from "../../state/runState";
import { Spinner, StatusMark } from "../ui";

/** A note with an action (Undo) stays long enough to use it. */
const ACTION_MS = 30_000;
const NOTE_MS = 8_000;

/**
 * The window's bottom line: the last thing the app did (with Undo when there is one) on
 * the left; unsaved edits and the tailoring run on the right. Errors are toasts instead.
 */
export function StatusBar() {
  const { busy, queuePosition } = useRunState();
  const editor = useEditorState();
  const applicant = useApplicantProfile();
  const unsaved = editor.dirty || applicant.dirty;
  return (
    <footer className="sticky bottom-0 z-20 flex h-(--rt-bar-bottom) items-center gap-4 border-t border-line bg-chrome px-4 text-xs text-ink-2 sm:px-6">
      <StatusMessage />
      {unsaved && (
        <span className="flex shrink-0 items-center gap-1.5">
          <StatusMark tone="attention" />
          Unsaved changes
        </span>
      )}
      {busy && (
        <Link to="/" className="flex shrink-0 items-center gap-1.5 hover:text-ink">
          <Spinner />
          {queuePosition ? `Queued (#${queuePosition})` : "Tailoring…"}
        </Link>
      )}
    </footer>
  );
}

/** The last success or info note, with its action (Undo) while it lasts. */
export function StatusMessage() {
  const { message, clear } = useStatusLine();
  useEffect(() => {
    if (!message || message.timeoutMs == null) return;
    const ms = Math.max(message.timeoutMs, message.action ? ACTION_MS : NOTE_MS);
    const timer = window.setTimeout(() => clear(message.id), ms);
    return () => window.clearTimeout(timer);
  }, [message, clear]);

  return (
    <p role="status" aria-live="polite" className="flex min-w-0 flex-1 items-center gap-2">
      {message && (
        <>
          {message.kind === "success" && <StatusMark tone="done" />}
          <span className="truncate" title={message.detail}>
            {message.title}
            {message.detail && <span className="text-ink-muted"> · {message.detail}</span>}
          </span>
          {message.action && (
            <button
              type="button"
              className="rt-link shrink-0 font-semibold"
              onClick={() => {
                message.action?.onClick();
                clear(message.id);
              }}
            >
              {message.action.label}
            </button>
          )}
        </>
      )}
    </p>
  );
}
