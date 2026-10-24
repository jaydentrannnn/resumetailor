import { useState } from "react";
import type { MailProposal, TrackerCard } from "../../api";
import { Button } from "../../components/ui";
import { SIGNAL_LABELS } from "../../lib/mailUpdates";
import { shortDate } from "../../lib/tracker";
import { useTracker } from "./trackerContext";

function what(proposal: MailProposal) {
  return proposal.signal ? SIGNAL_LABELS[proposal.signal] : "Job email";
}

/**
 * A pending email update on its card: what it says happened, the email it came from,
 * Accept / Dismiss. An email that contradicts what is recorded asks once more.
 */
export function CardEmail({ proposal }: { proposal: MailProposal }) {
  const tracker = useTracker();
  const [open, setOpen] = useState(false);
  const [confirm, setConfirm] = useState(false);
  const busy = tracker.busy === proposal.id;
  return (
    <div className="rounded-sm border border-line bg-panel px-2 py-1.5 text-xs">
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-baseline gap-1.5 text-left"
      >
        <span className="font-medium text-accent">Email</span>
        <span className="min-w-0 flex-1 truncate text-ink-2">{what(proposal)}</span>
        <span className="shrink-0 text-ink-muted">{shortDate(proposal.received_on)}</span>
      </button>
      {open && (
        <div className="mt-1.5 space-y-1">
          <p className="font-medium text-ink-2">{proposal.subject || "(no subject)"}</p>
          <p className="text-ink-muted">{proposal.from_domain}</p>
          {proposal.excerpt && <p className="line-clamp-4 text-ink-muted">{proposal.excerpt}</p>}
        </div>
      )}
      {proposal.flag && <p className="mt-1 text-attn">Check this: {proposal.flag}</p>}
      <div className="mt-1.5 flex items-center justify-end gap-1.5">
        <Button
          size="sm"
          variant="ghost"
          disabled={busy}
          onClick={() => void tracker.dismissEmail(proposal)}
        >
          Dismiss
        </Button>
        <Button
          size="sm"
          variant="secondary"
          disabled={busy}
          onClick={() => {
            if (proposal.flag && !confirm) setConfirm(true);
            else void tracker.acceptEmail(proposal);
          }}
        >
          {confirm ? "Record anyway" : "Accept"}
        </Button>
      </div>
    </div>
  );
}

/** A tray email dropped on this card: say what will be recorded, then record it. */
export function PendingEmailConfirm({
  card,
  proposal,
}: {
  card: TrackerCard;
  proposal: MailProposal;
}) {
  const tracker = useTracker();
  return (
    <div
      className="space-y-1.5 rounded-sm border border-accent bg-panel px-2 py-1.5 text-xs"
      role="group"
      aria-label="Confirm email"
    >
      <p className="text-ink-2">
        Record “{what(proposal)}” on {card.company}, from “{proposal.subject || "(no subject)"}”?
      </p>
      <div className="flex justify-end gap-1.5">
        <Button size="sm" variant="ghost" onClick={() => tracker.setPendingEmail(null)}>
          Cancel
        </Button>
        <Button
          size="sm"
          variant="secondary"
          onClick={() => {
            tracker.setPendingEmail(null);
            void tracker.acceptEmail(proposal, card.id);
          }}
        >
          Record
        </Button>
      </div>
    </div>
  );
}
