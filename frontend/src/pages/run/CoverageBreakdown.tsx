import type { CoverageFunnel, KeywordCoverage } from "../../api";
import { DataList, type DataItem } from "../../components/ui";

const GROUPS: { page: KeywordCoverage["page"]; label: string }[] = [
  { page: "not_selected", label: "In your resume, not on this page" },
  { page: "tag_only", label: "Backed on this page, never named" },
  { page: "inferred_only", label: "Only inferred on this page" },
];

/**
 * Where the required skills the page doesn't name were lost: never selected, backed by
 * an on-page bullet that doesn't name them, or backed only by inferred skills. Then
 * skills a rewrite named that its source bullet never stated or tagged.
 */
export function CoverageBreakdown({ funnel }: { funnel?: CoverageFunnel | null }) {
  if (!funnel) return null;
  const items: DataItem[] = GROUPS.flatMap(({ page, label }) => {
    const phrases = funnel.keywords.filter((k) => k.page === page).map((k) => k.phrase);
    return phrases.length ? [{ label, value: phrases.join(", ") }] : [];
  });
  const additions = [...new Set(funnel.unsupported_additions.map(([, skill]) => skill))];
  if (additions.length)
    items.push({ label: "Potentially unsupported additions", value: additions.join(", ") });
  if (!items.length) return null;
  return (
    // mt-5: the counters above are a `dl` whose m-0 cancels the parent's space-y.
    <div className="mt-5 border-t border-line pt-4">
      <DataList items={items} />
    </div>
  );
}
