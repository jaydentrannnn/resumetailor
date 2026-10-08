import type { KeywordGap, SkillsPlan, SkillSuggestion } from "../api";
import { recordSkillsCopy, skillsUrl } from "../api";
import { buttonClass } from "../lib/buttonClass";
import { CopyButton } from "./CopyButton";
import { ResultFrame } from "./ui";

const TIER_LABEL: Record<SkillSuggestion["tier"], string> = {
  required: "Required",
  preferred: "Preferred",
  additional: "Additional",
};

function pasteLine(plan: SkillsPlan): string {
  /** One comma-separated line — the highest-value affordance for a Skills field. */
  return plan.skills.map((s) => s.skill).join(", ");
}

/** Human-friendly label for one `SkillSuggestion.sources` entry — these are internal
 * evidence tags (`skills:<group label>`, `project:<entry id>`, `coursework`, `tag`),
 * not something to show verbatim. */
function friendlySource(source: string): string {
  if (source.startsWith("skills:")) return `Skills: ${source.slice("skills:".length)}`;
  if (source.startsWith("project:")) return "Project experience";
  if (source === "coursework") return "Coursework";
  if (source === "tag") return "Resume bullets";
  return source;
}

/** Full hover detail for one skill chip: the posting phrase it matches, why it was
 * picked, and where in the master resume it's evidenced — `jd_phrase`, `reason`, and
 * `sources` all traced back to the run instead of being dropped after selection. */
function chipTitle(s: SkillSuggestion): string | undefined {
  const parts: string[] = [];
  if (s.jd_phrase) parts.push(`Matches posting: "${s.jd_phrase}"`);
  if (s.reason) parts.push(s.reason);
  if (s.sources.length) {
    parts.push(`From: ${[...new Set(s.sources.map(friendlySource))].join(", ")}`);
  }
  return parts.length ? parts.join(" — ") : undefined;
}

function TierGroup({ tier, items }: { tier: SkillSuggestion["tier"]; items: SkillSuggestion[] }) {
  if (!items.length) return null;
  return (
    <div>
      <h4 className="rt-eyebrow">{TIER_LABEL[tier]}</h4>
      <ul className="mt-1.5 flex flex-wrap gap-1.5">
        {items.map((s) => (
          <li
            key={s.skill}
            title={chipTitle(s)}
            className="rounded-sm border border-line bg-field px-2.5 py-1 text-xs"
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
  embedded = false,
}: {
  plan: SkillsPlan;
  gaps: KeywordGap[];
  jobId: string;
  /** Inside the Tailor page's "Last result" tile: no box of its own. */
  embedded?: boolean;
}) {
  if (!plan.skills.length) {
    return (
      <ResultFrame embedded={embedded} title="Skills to list">
        <p className="text-sm text-ink-muted">No skills were selected for this run.</p>
      </ResultFrame>
    );
  }

  const required = plan.skills.filter((s) => s.tier === "required");
  const preferred = plan.skills.filter((s) => s.tier === "preferred");
  const additional = plan.skills.filter((s) => s.tier === "additional");
  const bandRank: Record<string, number> = {
    critical: 4,
    high: 3,
    meaningful: 2,
    preferred: 1,
    low_signal: 0,
  };
  const byBand = (a: KeywordGap, b: KeywordGap) =>
    (bandRank[b.band ?? "meaningful"] ?? 0) - (bandRank[a.band ?? "meaningful"] ?? 0);
  const annotate = (g: KeywordGap) =>
    g.band ? `${g.phrase} (${g.band}${g.evidence_tier ? `, ${g.evidence_tier}` : ""})` : g.phrase;
  const noEvidence = gaps
    .filter((g) => g.reason === "no_evidence")
    .slice()
    .sort(byBand);
  const claimableGaps = gaps
    .filter((g) => g.reason !== "no_evidence")
    .slice()
    .sort(byBand);

  return (
    <ResultFrame
      embedded={embedded}
      title="Skills to list"
      description="Ranked for application-form Skills fields. Every entry traces to the master resume — hover a chip for the posting's wording it matches."
      actions={
        <>
          <CopyButton
            label="Copy all"
            text={pasteLine(plan)}
            onCopied={() => void recordSkillsCopy(jobId).catch(() => undefined)}
          />
          <a href={skillsUrl(jobId)} className={buttonClass("secondary", "sm")}>
            Download .md
          </a>
        </>
      }
    >
      <div className="space-y-4">
        <TierGroup tier="required" items={required} />
        <TierGroup tier="preferred" items={preferred} />
        <TierGroup tier="additional" items={additional} />
      </div>

      {noEvidence.length > 0 && (
        <p className="mt-4 text-sm text-attn">
          The posting also asks for: {noEvidence.map(annotate).join(", ")} — not supported by the
          master resume, so not suggested above.
        </p>
      )}

      {claimableGaps.length > 0 && (
        <div className="mt-2 text-sm text-ink-muted">
          {claimableGaps.map((g) => (
            <p key={g.canonical}>
              {annotate(g)}: claimable but untagged — consider adding the tag (
              {g.evidence.join("; ")})
            </p>
          ))}
        </div>
      )}

      {plan.warnings.map((w) => (
        <p key={w} className="mt-3 text-sm text-ink-muted">
          {w}
        </p>
      ))}

      <p className="mt-4 text-xs text-ink-muted">
        Model: <span className="font-mono">{plan.model}</span>
      </p>
    </ResultFrame>
  );
}
