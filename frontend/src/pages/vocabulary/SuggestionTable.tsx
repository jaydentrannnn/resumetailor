import { DataTable } from "../../components/TableControls";
import { StatusChip } from "../../components/ui";
import type { useSuggestionsSection } from "./useSuggestionsSection";
type State = ReturnType<typeof useSuggestionsSection>;
export function SuggestionTable({
  pageProposals,
  selected,
  setSelected,
  busy,
  impactByAlias,
}: Pick<State, "pageProposals" | "selected" | "setSelected" | "busy" | "impactByAlias">) {
  return (
    <div className="my-4 bg-panel [&_thead]:bg-sunken">
      <DataTable
        bare
        rows={pageProposals}
        id={(proposal) => proposal.id}
        selected={selected}
        onSelected={setSelected}
        selectable={() => !busy}
        sort=""
        direction="asc"
        onSort={() => {}}
        empty="No suggestions."
        rowLabel={(p) => p.alias || p.verb || p.id}
        columns={[
          {
            id: "suggestion",
            heading: "Suggestion",
            cell: (p) => (
              <span className="font-mono">
                {p.alias || p.verb} → {p.canonical || p.family}
              </span>
            ),
          },
          {
            id: "rationale",
            heading: "Reason",
            className: "w-[40%]",
            cell: (p) => <span className="text-xs text-ink-muted">{p.rationale}</span>,
          },
          {
            id: "impact",
            heading: "Impact",
            cell: (p) => {
              const impact = p.alias ? impactByAlias[p.alias] : undefined;
              const rewrites = impact && impact.affected_tags.length > 0;
              return p.kind === "tag_alias" ? (
                <div className="space-y-2">
                  <StatusChip tone={rewrites ? "attention" : "neutral"}>
                    {rewrites
                      ? `Rewrites ${impact.affected_tags.length} tag${impact.affected_tags.length === 1 ? "" : "s"}`
                      : "Additive"}
                  </StatusChip>
                  {rewrites && (
                    <p className="text-xs text-ink-muted">
                      Affects: {impact.affected_bullets.map(([label]) => label).join(", ")}
                    </p>
                  )}
                </div>
              ) : (
                <StatusChip tone="neutral">Verb family</StatusChip>
              );
            },
          },
        ]}
      />
    </div>
  );
}
