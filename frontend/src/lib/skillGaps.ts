import type { SkillGap } from "../api";

export type GapItem = { label: string; count: number; title: string };

/** The first `max` skills, each with how many postings asked and which companies. */
export function gapItems(gaps: SkillGap[], max = 5): GapItem[] {
  return gaps.slice(0, max).map((gap) => {
    const more = gap.jobs - gap.companies.length;
    const names =
      more > 0 && gap.companies.length ? [...gap.companies, `${more} more`] : gap.companies;
    const asked = `${gap.jobs} ${gap.jobs === 1 ? "posting" : "postings"}`;
    return {
      label: gap.skill,
      count: gap.jobs,
      title: names.length ? `${asked}: ${joinNames(names)}` : asked,
    };
  });
}

function joinNames(names: string[]): string {
  return names.length < 2 ? names.join("") : `${names.slice(0, -1).join(", ")} and ${names.at(-1)}`;
}
