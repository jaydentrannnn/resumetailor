import { useState } from "react";
import type { MailProposal, MailSignal } from "../../api";
import { Button } from "../../components/ui";
import { SIGNAL_LABELS, SIGNALS } from "../../lib/mailUpdates";

/**
 * One job email: who it is from, what it says happened, and the application it is about.
 * The type and the application can be changed before Accept; an unmatched email must be
 * assigned first. A flagged email (it contradicts what is recorded) says why.
 */
export function EmailProposalRow({
  proposal,
  busy,
  onAccept,
  onDismiss,
}: {
  proposal: MailProposal;
  busy: boolean;
  onAccept: (choice: { signal: MailSignal; app_id: string }) => void;
  onDismiss: () => void;
}) {
  const [signal, setSignal] = useState<MailSignal>(proposal.signal ?? "sent");
  const [appId, setAppId] = useState(proposal.app_id ?? "");
  const title = proposal.app_id
    ? `${proposal.company} · ${proposal.role}`
    : "Not matched to an application";
  return (
    <li className="space-y-2 py-3 text-[13px]">
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <span className="min-w-0 flex-1 truncate font-medium text-ink">{title}</span>
        <span className="shrink-0 text-xs text-ink-muted">
          {proposal.stage ? `${proposal.stage} → ` : ""}
          {SIGNAL_LABELS[signal]}
        </span>
      </div>
      <div className="text-xs text-ink-2">
        <span className="font-medium">{proposal.subject || "(no subject)"}</span>
        <span className="text-ink-muted">
          {" "}
          · {proposal.received_on ?? "date unknown"} · {proposal.from_domain}
        </span>
      </div>
      {proposal.excerpt && (
        <p className="line-clamp-3 text-xs text-ink-muted">{proposal.excerpt}</p>
      )}
      {proposal.flag && <p className="text-xs text-attn">Check this: {proposal.flag}</p>}
      <div className="flex flex-wrap items-center gap-2">
        <select
          aria-label="What happened"
          className="field w-auto text-xs"
          value={signal}
          onChange={(e) => setSignal(e.target.value as MailSignal)}
        >
          {SIGNALS.map((key) => (
            <option key={key} value={key}>
              {SIGNAL_LABELS[key]}
            </option>
          ))}
        </select>
        {proposal.options.length > 0 && (
          <select
            aria-label="Application"
            className="field w-auto max-w-72 text-xs"
            value={appId}
            onChange={(e) => setAppId(e.target.value)}
          >
            {!proposal.app_id && <option value="">Pick the application…</option>}
            {proposal.options.map((option) => (
              <option key={option.id} value={option.id}>
                {option.company} · {option.role} ({option.stage})
              </option>
            ))}
          </select>
        )}
        <span className="flex-1" />
        <Button size="sm" variant="ghost" disabled={busy} onClick={onDismiss}>
          Dismiss
        </Button>
        <Button
          size="sm"
          variant="plain"
          disabled={busy || !appId}
          onClick={() => onAccept({ signal, app_id: appId })}
        >
          Accept
        </Button>
      </div>
    </li>
  );
}
