import type { SourceFilters, WorkTypes } from "../../api";
import { Switch } from "../../components/ui";
import { ALL_WORK_TYPES } from "../../lib/globalFilters";
import { ChipInput } from "./ChipInput";

const WORK_TYPES: [keyof WorkTypes, string][] = [
  ["onsite", "On-site"],
  ["hybrid", "Hybrid"],
  ["remote", "Remote"],
];

/** Work-type switches and the countries Find keeps (`apply.discovery.posting_location`). */
export function LocationPolicyFields({
  filters,
  onChange,
}: {
  filters: SourceFilters;
  onChange: (next: SourceFilters) => void;
}) {
  const work = { ...ALL_WORK_TYPES, ...filters.work_types };
  return (
    <div className="space-y-4">
      <div className="text-xs">
        <p className="mb-1.5 font-medium">Ways of working</p>
        <div className="flex flex-wrap gap-x-5 gap-y-2">
          {WORK_TYPES.map(([key, label]) => (
            <label key={key} className="flex items-center gap-2 text-sm font-medium">
              <Switch
                checked={work[key]}
                onChange={(on) => onChange({ ...filters, work_types: { ...work, [key]: on } })}
              />
              {label}
            </label>
          ))}
        </div>
      </div>
      <ChipInput
        label="Countries"
        noun="country"
        chips={filters.countries ?? []}
        placeholder="e.g. United States (empty uses the countries in your profile)"
        onChange={(countries) => onChange({ ...filters, countries })}
      />
      <label className="flex items-start gap-2.5 text-sm font-medium">
        <Switch
          checked={filters.other_countries !== false}
          onChange={(on) => onChange({ ...filters, other_countries: on })}
        />
        <span>
          Also keep other countries
          <span className="block text-xs font-normal text-ink-muted">
            Applications there say you need visa sponsorship.
          </span>
        </span>
      </label>
    </div>
  );
}
