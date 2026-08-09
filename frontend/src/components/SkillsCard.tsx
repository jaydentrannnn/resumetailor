import type { KeywordGap, SkillsPlan, SkillSuggestion } from "../api";
import { skillsUrl } from "../api";
import { CopyButton } from "./CopyButton";

const TIER_LABEL: Record<SkillSuggestion["tier"], string> = {
  required: "Required",
  preferred: "Preferred",
  additional: "Additional",
};

function pasteLine(plan: SkillsPlan): string {
  /** One comma-separated line — the highest-value affordance for a Skills field. */
  return plan.skills.map((s) => s.skill).join(", ");
}

function TierGroup({ tier, items }: { tier: SkillSuggestion["tier"]; items: SkillSuggestion[] }) {
  if (!items.length) return null;
  return (
    <div>
      <h3 className="text-xs font-semibold uppercase tracking-wide text-ink-muted">
        {TIER_LABEL[tier]}
      </h3>
      <ul className="mt-1.5 flex flex-wrap gap-1.5">
        {items.map((s) => (
          <li
            key={s.skill}
            title={s.jd_phrase ? `Matches posting: "${s.jd_phrase}"` : undefined}
            className="rounded-full border border-line bg-paper/40 px-2.5 py-1 text-xs"
          >
            {s.skill}
          </li>
        ))}
      </ul>
    </div>
  );
}

/**
 * Copy-paste tile for a tailored skills list, sitting below Application experience,
 * beside the report, on the Tailor page's final row.
 *
 * Ranked required/preferred/additional in code (`skills.py`'s tiering), not by the
 * model. `gaps` is `RunReport.gaps`, already computed once by `report.diagnose_gaps` —
 * this tile does not recompute it, only reads the `no_evidence` slice as "cannot claim"
 * and the untagged/near-miss slices as a secondary hint.
 */
export function SkillsCard({
  plan,
  gaps,
  jobId,
}: {
  plan: SkillsPlan;
  gaps: KeywordGap[];
  jobId: string;
}) {
  if (!plan.skills.length) {
    return (
      <section className="rounded-xl border border-line bg-panel p-5 shadow-sm">
        <h2 className="font-display text-xl font-semibold">Skills to list</h2>
        <p className="mt-2 text-sm text-ink-muted">
          No skills were selected for this run.
        </p>
      </section>
    );
  }

  const required = plan.skills.filter((s) => s.tier === "required");
  const preferred = plan.skills.filter((s) => s.tier === "preferred");
  const additional = plan.skills.filter((s) => s.tier === "additional");
  const noEvidence = gaps.filter((g) => g.reason === "no_evidence");
  const claimableGaps = gaps.filter((g) => g.reason !== "no_evidence");

  return (
    <section className="rounded-xl border border-line bg-panel p-5 shadow-sm">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="font-display text-xl font-semibold">Skills to list</h2>
          <p className="mt-1 text-sm text-ink-muted">
            Ranked for application-form Skills fields. Every entry traces to the master
            resume — hover a chip for the posting's wording it matches.
          </p>
        </div>
        <div className="flex shrink-0 flex-wrap gap-2">
          <CopyButton label="Copy all" text={pasteLine(plan)} />
          <a
            href={skillsUrl(jobId)}
            className="shrink-0 rounded-md border border-line px-2.5 py-1 text-xs font-medium text-ink-muted hover:border-accent hover:text-accent"
          >
            Download .md
          </a>
        </div>
      </div>

      <div className="mt-4 space-y-3">
        <TierGroup tier="required" items={required} />
        <TierGroup tier="preferred" items={preferred} />
        <TierGroup tier="additional" items={additional} />
      </div>

      {noEvidence.length > 0 && (
        <p className="mt-3 rounded-md bg-warn-soft px-3 py-2 text-sm text-warn">
          The posting also asks for: {noEvidence.map((g) => g.phrase).join(", ")} — not
          supported by the master resume, so not suggested above.
        </p>
      )}

      {claimableGaps.length > 0 && (
        <div className="mt-2 text-sm text-ink-muted">
          {claimableGaps.map((g) => (
            <p key={g.canonical}>
              {g.phrase}: claimable but untagged — consider adding the tag (
              {g.evidence.join("; ")})
            </p>
          ))}
        </div>
      )}

      {plan.warnings.map((w) => (
        <p key={w} className="mt-3 rounded-md bg-warn-soft px-3 py-2 text-sm text-warn">
          {w}
        </p>
      ))}

      <p className="mt-3 text-xs text-ink-muted">Model: {plan.model}</p>
    </section>
  );
}
