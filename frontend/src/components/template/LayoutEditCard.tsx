import { useLayoutEditSession } from "../../lib/useLayoutEditSession";
import { useConfirm } from "../../state/confirmState";
import { Button, Tile } from "../ui";

function savedLabel(iso: string | null): string {
  if (!iso) return "";
  try {
    return new Date(iso).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
  } catch {
    return iso;
  }
}

/**
 * Template page › Edit layout in Word (desktop app only): opens a copy of the template
 * with «fields» in place of the words, then reads the saved file back into the template
 * wizard. Nothing changes until the wizard's Install.
 */
export function LayoutEditCard() {
  const { desktop, status, busy, error, start, reopen, review, discard } =
    useLayoutEditSession();
  const { confirm } = useConfirm();
  if (!desktop) return null;

  const onDiscard = async () => {
    const ok = await confirm({
      title: "Discard layout edits?",
      message:
        "The layout file is deleted and your template stays as it is. Close it in Word first if it is still open.",
      confirmLabel: "Discard",
      tone: "danger",
    });
    if (ok) await discard();
  };

  let message: string;
  if (!status.active) {
    message =
      "Change fonts, sizes, spacing, margins or where each field sits, in Word. You see «fields» instead of your words; save the file and come back here to review it.";
  } else if (status.changed) {
    message = `Saved at ${savedLabel(status.saved_at)}. Review the changes, then install them as a new template.${
      status.editor_open ? " You can keep Word open and save again." : ""
    }`;
  } else {
    message = status.editor_open
      ? "Open in Word. Save the file when you're done — this page notices the save."
      : "Waiting for the layout file to open. If it didn't, open it again.";
  }

  return (
    <Tile aria-label="Edit layout in Word">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <h2 className="rt-tile-title">Edit layout in Word</h2>
          <p className="mt-1 text-sm text-ink-muted" aria-live="polite">
            {message}
          </p>
          {error && <p className="mt-3 text-sm text-danger">{error}</p>}
        </div>
        <div className="flex flex-wrap gap-2">
          {!status.active && (
            <Button variant="secondary" disabled={busy} onClick={() => void start()}>
              Edit layout in Word
            </Button>
          )}
          {status.active && (
            <>
              <Button
                variant="primary"
                disabled={busy || !status.changed}
                onClick={() => void review()}
              >
                Review changes
              </Button>
              <Button variant="plain" disabled={busy} onClick={() => void reopen()}>
                Open again
              </Button>
              <Button variant="danger" disabled={busy} onClick={() => void onDiscard()}>
                Discard
              </Button>
            </>
          )}
        </div>
      </div>
    </Tile>
  );
}
