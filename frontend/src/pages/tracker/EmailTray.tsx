import type { MailProposal } from "../../api";
import { RowActionsMenu } from "../../components/TableControls";
import { Button } from "../../components/ui";
import { SIGNAL_LABELS } from "../../lib/mailUpdates";
import { shortDate } from "../../lib/tracker";
import { useTracker } from "./trackerContext";

/**
 * Email updates with no card on the board. Drag one onto the application it is about
 * (the card asks before recording), or use "Assign to…"; one already matched to an
 * application outside Done can be accepted as it is.
 */
export function EmailTray({ proposals }: { proposals: MailProposal[] }) {
  const tracker = useTracker();
  if (proposals.length === 0) return null;
  return (
    <section aria-label="Emails to assign" className="rounded-md border border-line bg-panel p-3">
      <h2 className="mb-2 text-xs font-semibold text-ink-2">
        Emails to assign <span className="font-mono font-normal text-ink-muted">{proposals.length}</span>
        <span className="ml-2 font-normal text-ink-muted">Drag one onto its application.</span>
      </h2>
      <ul className="flex flex-wrap gap-2">
        {proposals.map((proposal) => (
          <li
            key={proposal.id}
            draggable
            data-tracker-email={proposal.id}
            onDragStart={(e) => {
              e.dataTransfer.effectAllowed = "move";
              e.dataTransfer.setData("text/plain", proposal.id);
              tracker.setDrag({ kind: "email", proposal });
            }}
            onDragEnd={() => tracker.setDrag(null)}
            className="flex min-w-0 max-w-full cursor-grab items-center gap-2 rounded-sm sm:max-w-sm border border-line bg-paper px-2 py-1.5 text-xs active:cursor-grabbing"
          >
            <div className="min-w-0 flex-1">
              <p className="truncate font-medium text-ink">
                {proposal.signal ? SIGNAL_LABELS[proposal.signal] : "Job email"}
                {proposal.app_id && proposal.company ? ` · ${proposal.company}` : ""}
              </p>
              <p className="truncate text-ink-muted">
                {proposal.subject || "(no subject)"} · {shortDate(proposal.received_on) || proposal.from_domain}
              </p>
            </div>
            {proposal.app_id ? (
              <Button
                size="sm"
                variant="secondary"
                disabled={tracker.busy === proposal.id}
                onClick={() => void tracker.acceptEmail(proposal)}
              >
                Accept
              </Button>
            ) : null}
            <RowActionsMenu
              label={`Email actions: ${proposal.subject}`}
              items={[
                ...proposal.options.map((option) => ({
                  label: `Assign to ${option.company} · ${option.role}`,
                  action: () => void tracker.acceptEmail(proposal, option.id),
                })),
                { label: "Dismiss", action: () => void tracker.dismissEmail(proposal) },
              ]}
            />
          </li>
        ))}
      </ul>
    </section>
  );
}
