import { sessionMessage } from "../../../lib/layoutEditMessage";
import { useLayoutEditSession } from "../../../lib/useLayoutEditSession";
import { useConfirm } from "../../../state/confirmState";
import { Button } from "../../ui";

/**
 * Edit layout in Word (desktop app only): opens a copy of the template with «fields» in
 * place of the words, then reads the saved file back into the template wizard. Nothing
 * changes until the wizard's Install. Sits in the Resume view's Look section.
 */
export function LayoutEditSection() {
  const { desktop, status, busy, error, start, reopen, review, discard } = useLayoutEditSession();
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

  return (
    <div aria-label="Edit layout in Word" role="group">
      <p className="text-xs text-ink-muted" aria-live="polite">
        {sessionMessage(status)}
      </p>
      {error && <p className="mt-2 text-xs text-danger">{error}</p>}
      <div className="mt-2 flex flex-wrap gap-2">
        {!status.active && (
          <Button variant="plain" disabled={busy} onClick={() => void start()}>
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
  );
}
