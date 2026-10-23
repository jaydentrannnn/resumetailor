import type { EvidenceProposal } from "../../../api";
import { Button, StatusChip } from "../../../components/ui";
import { PROPOSAL_KIND_LABELS, STATE_LABELS } from "../../../lib/evidence";

/**
 * One proposed item: what it is, where it would go, the source's own words and, for an
 * inferred item, the question to answer first. Pending items offer Add to resume,
 * Matching only (skills) and Dismiss; decided ones offer Undo where that makes sense.
 */
export function ProposalCard({
  proposal,
  place,
  busy,
  addBlocked,
  onAdd,
  onMatching,
  onDismiss,
  onReopen,
}: {
  proposal: EvidenceProposal;
  /** Where it would go, in words ("Intern, Acme"). */
  place: string;
  busy: boolean;
  /** Why Add is unavailable right now (unsaved resume edits), if it is. */
  addBlocked: string;
  onAdd: () => void;
  onMatching: () => void;
  onDismiss: () => void;
  onReopen: () => void;
}) {
  const pending = proposal.state === "pending";
  const inferred = proposal.basis === "inferred";
  return (
    <li className="space-y-1.5 py-3 first:pt-0">
      <div className="flex flex-wrap items-center gap-2 text-xs text-ink-muted">
        <span className="font-medium text-ink-2">{PROPOSAL_KIND_LABELS[proposal.kind]}</span>
        {place && <span>· {place}</span>}
        <StatusChip tone={inferred ? "attention" : "neutral"}>
          {inferred ? "Suggested, not stated" : "Stated in the source"}
        </StatusChip>
        {!pending && <StatusChip tone="muted">{STATE_LABELS[proposal.state]}</StatusChip>}
      </div>
      <p className="text-sm text-ink">{proposal.text}</p>
      <p className="text-xs italic text-ink-muted">“{proposal.excerpt}”</p>
      {inferred && proposal.question && (
        <p className="text-xs text-ink-2">
          <span className="font-medium">Answer first:</span> {proposal.question}
        </p>
      )}
      {pending ? (
        <div className="flex flex-wrap items-center gap-2 pt-1">
          <Button
            size="sm"
            variant="primary"
            disabled={busy || Boolean(addBlocked)}
            onClick={onAdd}
          >
            Add to resume…
          </Button>
          {proposal.kind === "skill" && (
            <Button
              size="sm"
              variant="secondary"
              loading={busy}
              disabled={busy}
              onClick={onMatching}
            >
              Matching only
            </Button>
          )}
          <Button size="sm" variant="ghost" disabled={busy} onClick={onDismiss}>
            Dismiss
          </Button>
          {addBlocked && <span className="text-xs text-ink-muted">{addBlocked}</span>}
        </div>
      ) : (
        proposal.state !== "added" && (
          <Button size="sm" variant="ghost" disabled={busy} onClick={onReopen}>
            Undo
          </Button>
        )
      )}
    </li>
  );
}
