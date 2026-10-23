import { useEffect, useState } from "react";
import {
  acceptMailProposal,
  dismissMailProposal,
  getMailProposals,
  type MailProposal,
  type MailSignal,
} from "../../api";
import { AttentionRow } from "../../components/ProfileGapsNotice";
import { Button, Modal } from "../../components/ui";
import { describe } from "../../lib/errors";
import { mailSummary, readyToAccept } from "../../lib/mailUpdates";
import { useToast } from "../../lib/toast";
import { EmailProposalRow } from "./EmailProposalRow";

/**
 * One Apply-page line when Claude Desktop has handed over job emails (`/api/mail/*`).
 * Review lists each with what it says happened; nothing reaches an application until it
 * is accepted here. "Accept all matched" skips unmatched and flagged emails.
 */
export function EmailUpdatesNotice({
  revision,
  onChanged,
}: {
  revision: number;
  onChanged: () => void;
}) {
  const toast = useToast();
  const [proposals, setProposals] = useState<MailProposal[] | null>(null);
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [reload, setReload] = useState(0);

  useEffect(() => {
    let live = true;
    getMailProposals()
      .then((result) => live && setProposals(result.proposals))
      .catch(() => undefined);
    return () => {
      live = false;
    };
  }, [revision, reload]);

  if (!proposals || proposals.length === 0) return null;
  const ready = proposals.filter(readyToAccept);

  /** Runs one change, then reloads the list; `work` returns the success toast, if any. */
  async function run(work: () => Promise<string | null>) {
    setBusy(true);
    try {
      const message = await work();
      if (message) toast.success(message);
    } catch (reason) {
      toast.error("Could not save", describe(reason).detail);
    } finally {
      setBusy(false);
      setReload((n) => n + 1);
      onChanged();
    }
  }

  const accept = (p: MailProposal, choice: { signal: MailSignal; app_id: string }) =>
    run(async () => {
      await acceptMailProposal(p.id, choice);
      return "Recorded from email";
    });
  const dismiss = (p: MailProposal) =>
    run(async () => {
      await dismissMailProposal(p.id);
      return null;
    });
  const acceptAll = () =>
    run(async () => {
      for (const p of ready) await acceptMailProposal(p.id);
      return `Recorded ${ready.length} from email`;
    });

  return (
    <>
      <AttentionRow
        label="Email updates"
        text={mailSummary(proposals)}
        action={
          <Button variant="plain" size="sm" className="rt-row-action" onClick={() => setOpen(true)}>
            Review
          </Button>
        }
      />
      {open && (
        <Modal
          title={`Email updates (${proposals.length})`}
          onClose={() => setOpen(false)}
          size="lg"
        >
          <div className="space-y-3">
            <p className="text-xs text-ink-muted">
              Read from your mail by Claude Desktop. Check each one; emails can be wrong or about
              someone else's application.
            </p>
            <ul className="divide-y divide-line">
              {proposals.map((p) => (
                <EmailProposalRow
                  key={p.id}
                  proposal={p}
                  busy={busy}
                  onAccept={(choice) => void accept(p, choice)}
                  onDismiss={() => void dismiss(p)}
                />
              ))}
            </ul>
            {ready.length > 1 && (
              <Button
                size="sm"
                variant="secondary"
                disabled={busy}
                onClick={() => void acceptAll()}
              >
                Accept all {ready.length} matched
              </Button>
            )}
          </div>
        </Modal>
      )}
    </>
  );
}
