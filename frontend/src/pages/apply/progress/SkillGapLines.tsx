import type { SkillGap, SkillGaps } from "../../../api";
import { gapItems } from "../../../lib/skillGaps";

/** "Most asked, not in your resume: Kubernetes 4 · Tableau 3", and the same for skills
 * the resume has that the page didn't show. Hover a skill for who asked. */
export function SkillGapLines({ gaps }: { gaps: SkillGaps | null }) {
  if (!gaps || (!gaps.gaps.length && !gaps.not_shown.length)) return null;
  return (
    <div className="basis-full space-y-1 text-sm text-ink-2">
      <GapLine heading="Most asked, not in your resume:" gaps={gaps.gaps} />
      <GapLine heading="In your resume, not on the page:" gaps={gaps.not_shown} />
      <p className="text-xs text-ink-muted">
        From {gaps.counted} tailored {gaps.counted === 1 ? "posting" : "postings"} you went after;
        near-misses count more.
      </p>
    </div>
  );
}

function GapLine({ heading, gaps }: { heading: string; gaps: SkillGap[] }) {
  if (!gaps.length) return null;
  return (
    <p>
      <span className="font-medium text-ink">{heading}</span>{" "}
      {gapItems(gaps).map((item, index) => (
        <span key={item.label} title={item.title}>
          {index > 0 && " · "}
          {item.label} <span className="text-ink-muted">{item.count}</span>
        </span>
      ))}
    </p>
  );
}
