import { useState } from "react";
import type { MailProposal } from "../../api";
import { Button } from "../../components/ui";
import { readSeenAuto, shortDate, writeSeenAuto } from "../../lib/tracker";
import { useTracker } from "./trackerContext";

/**
 * Rejections the mailbox check closed on its own, each with Undo. "Got it" hides the
 * ones listed on this browser; a later close shows the notice again.
 */
export function AutoClosedNotice({ proposals, workspaceId }: { proposals: MailProposal[]; workspaceId: string }) {
  const { busy, undoAutoClose } = useTracker();
  const [seen, setSeen] = useState<string[]>(() => readSeenAuto(workspaceId));
  const fresh = proposals.filter((p) => !seen.includes(p.id));
  if (fresh.length === 0) return null;
  const gotIt = () => {
    const next = [...seen, ...fresh.map((p) => p.id)];
    setSeen(next);
    writeSeenAuto(workspaceId, next);
  };
  return (
    <section aria-label="Closed from email" className="rounded-md border border-line bg-panel p-3">
      <div className="mb-2 flex flex-wrap items-center gap-2">
        <h2 className="text-xs font-semibold text-ink-2">
          {fresh.length} closed from email
          <span className="ml-2 font-normal text-ink-muted">Rejections the app was sure of. Undo any that are wrong.</span>
        </h2>
        <Button size="sm" variant="plain" className="ml-auto" onClick={gotIt}>
          Got it
        </Button>
      </div>
      <ul className="divide-y divide-line">
        {fresh.map((proposal) => (
          <li key={proposal.id} className="flex min-w-0 items-center gap-3 py-1.5 text-xs">
            <div className="min-w-0 flex-1">
              <p className="truncate font-medium text-ink">
                {proposal.company} · {proposal.role}
              </p>
              <p className="truncate text-ink-muted">
                {proposal.subject || "(no subject)"} · {shortDate(proposal.received_on) || proposal.from_domain}
              </p>
            </div>
            <Button
              size="sm"
              variant="secondary"
              disabled={busy === proposal.id}
              onClick={() => void undoAutoClose(proposal)}
            >
              Undo
            </Button>
          </li>
        ))}
      </ul>
    </section>
  );
}
