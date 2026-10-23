import type { EvidenceProposal, EvidenceSource } from "../../../api";
import { entryLabel, groupProposals } from "../../../lib/evidence";
import type { MasterResume } from "../../../lib/resumeEdit";
import type { EvidenceActions } from "../../../lib/useEvidence";
import { ProposalCard } from "./ProposalCard";

/** Waiting items grouped by source, then what was already decided. */
export function ProposalList({
  sources,
  proposals,
  resume,
  evidence,
  addBlocked,
  onAdd,
  run,
}: {
  sources: EvidenceSource[];
  proposals: EvidenceProposal[];
  resume: MasterResume | null;
  evidence: EvidenceActions;
  addBlocked: string;
  onAdd: (proposal: EvidenceProposal) => void;
  run: (action: () => Promise<unknown>, failed: string) => void;
}) {
  const { pending, decided } = groupProposals(sources, proposals);
  const card = (proposal: EvidenceProposal) => (
    <ProposalCard
      key={proposal.id}
      proposal={proposal}
      place={proposal.target_entry_id ? entryLabel(resume, proposal.target_entry_id) : ""}
      busy={evidence.busy !== null}
      addBlocked={addBlocked}
      onAdd={() => onAdd(proposal)}
      onMatching={() => run(() => evidence.keepForMatching(proposal.id), "Could not keep it")}
      onDismiss={() => run(() => evidence.dismiss(proposal.id), "Could not dismiss")}
      onReopen={() => run(() => evidence.reopen(proposal.id), "Could not undo")}
    />
  );
  return (
    <div className="space-y-5">
      {pending.length === 0 && (
        <p className="text-sm text-ink-muted">
          Nothing waiting. Scan a source to see what it could add to your resume.
        </p>
      )}
      {pending.map((group) => (
        <section key={group.source?.id ?? "removed"} className="space-y-2">
          <h3 className="text-xs font-medium uppercase tracking-wide text-ink-muted">
            {group.source?.title ?? "Removed source"}
          </h3>
          <ul className="divide-y divide-line">{group.items.map(card)}</ul>
        </section>
      ))}
      {decided.length > 0 && (
        <details className="text-sm">
          <summary className="cursor-pointer text-xs text-ink-muted">
            Already decided ({decided.length})
          </summary>
          <ul className="mt-2 divide-y divide-line">{decided.map(card)}</ul>
        </details>
      )}
    </div>
  );
}
