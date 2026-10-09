import { useId } from "react";
import type { ApplySettings } from "../../api";
import { Button, DataList, Tile } from "../../components/ui";
import { eligibilitySummary, globalFiltersOf, shortList } from "../../lib/globalFilters";
import { GlobalFiltersForm } from "./GlobalFiltersForm";

/**
 * "Filters for every source", above the source tiles. Like the Tailor page's Options tile:
 * collapsed it lists the current settings; "Change" opens the form in the same tile.
 * `editing` lives in the parent so a source panel's "Change them there" can open it.
 */
export function GlobalFiltersTile({
  apply,
  onChange,
  editing,
  onEditingChange,
}: {
  apply: ApplySettings;
  onChange: (patch: Partial<ApplySettings>) => void;
  editing: boolean;
  onEditingChange: (on: boolean) => void;
}) {
  const formId = useId();
  const filters = globalFiltersOf(apply);
  return (
    <Tile
      id="every-source-filters"
      title="Filters for every source"
      meta={`Used by all ${apply.sources.length} sources`}
      actions={
        <Button
          size="sm"
          aria-expanded={editing}
          aria-controls={formId}
          onClick={() => onEditingChange(!editing)}
        >
          {editing ? "Done" : "Change"}
        </Button>
      }
    >
      {editing ? (
        <div id={formId}>
          <p className="mb-4 text-sm text-ink-muted">
            Every job list, search and watchlist uses these. A source can add its own words on top.
          </p>
          <GlobalFiltersForm apply={apply} onChange={onChange} />
        </div>
      ) : (
        <DataList
          className="gap-x-12"
          items={[
            { label: "Keep titles", value: shortList(filters.include, "Any title") },
            { label: "Skip titles", value: shortList(filters.exclude, "Nothing") },
            { label: "Locations", value: shortList(filters.locations, "Anywhere") },
            {
              label: "Posted within",
              value: `${apply.max_age_days} day${apply.max_age_days === 1 ? "" : "s"}`,
            },
            { label: "Eligibility", value: eligibilitySummary(apply) },
          ]}
        />
      )}
    </Tile>
  );
}
