import type { ApplySettings } from "../../api";
import { Switch, TileSection } from "../../components/ui";
import { globalFiltersOf } from "../../lib/globalFilters";
import { AgeWindowPicker } from "./AgeWindowPicker";
import { ChipInput } from "./ChipInput";

const ELIGIBILITY_SWITCHES = [
  ["exclude_no_sponsorship", "Skip jobs that won't sponsor a visa"],
  ["exclude_citizenship_required", "Skip jobs that require citizenship"],
  ["exclude_advanced_degree", "Skip jobs that require a master's or PhD"],
] as const;

/** A whole number from a box, clamped to 0–20 years. */
const years = (value: string) => Math.min(20, Math.max(0, Number(value) || 0));

/** The editor inside "Filters for every source": shared words, posting age and eligibility. */
export function GlobalFiltersForm({
  apply,
  onChange,
}: {
  apply: ApplySettings;
  onChange: (patch: Partial<ApplySettings>) => void;
}) {
  const filters = globalFiltersOf(apply);
  const setWords = (key: keyof typeof filters) => (words: string[]) =>
    onChange({ source_filters: { ...filters, [key]: words } });
  const eligibility = apply.eligibility;

  return (
    <div className="space-y-5">
      <TileSection title="Titles and places">
        <div className="space-y-4">
          <ChipInput
            label="Keep titles containing"
            noun="keyword"
            chips={filters.include}
            placeholder="e.g. analyst (empty keeps every title)"
            onChange={setWords("include")}
          />
          <ChipInput
            label="Skip titles containing"
            noun="skipped word"
            chips={filters.exclude}
            placeholder="e.g. senior"
            onChange={setWords("exclude")}
          />
          <ChipInput
            label="Only these locations"
            noun="location"
            chips={filters.locations}
            placeholder="e.g. New York, Remote (empty means anywhere)"
            onChange={setWords("locations")}
          />
          <div className="text-xs">
            <p className="mb-1 font-medium">Only postings from the last</p>
            <AgeWindowPicker
              ariaLabel="Posting age in days"
              value={apply.max_age_days}
              onChange={(days) => onChange({ max_age_days: days })}
            />
            <p className="mt-1 text-ink-muted">A source with a longer limit of its own keeps it.</p>
          </div>
        </div>
      </TileSection>
      <TileSection title="Eligibility">
        <div className="space-y-4">
          <div className="space-y-2.5">
            {ELIGIBILITY_SWITCHES.map(([key, label]) => (
              <label key={key} className="flex items-center gap-2.5 text-sm font-medium">
                <Switch checked={apply[key]} onChange={(on) => onChange({ [key]: on })} />
                {label}
              </label>
            ))}
          </div>
          <div className="grid gap-4 text-sm sm:grid-cols-2">
            <label className="block">
              <span className="mb-1 block">Skip jobs asking for at least</span>
              <input
                type="number"
                min={0}
                max={20}
                className="field mr-1.5 inline-block w-16"
                value={eligibility.hard_reject_years}
                onChange={(e) =>
                  onChange({
                    eligibility: { ...eligibility, hard_reject_years: years(e.target.value) },
                  })
                }
              />
              years' experience
            </label>
            <label className="block">
              <span className="mb-1 block">Flag jobs asking for at least</span>
              <input
                type="number"
                min={0}
                max={20}
                className="field mr-1.5 inline-block w-16"
                value={eligibility.flag_years}
                onChange={(e) =>
                  onChange({ eligibility: { ...eligibility, flag_years: years(e.target.value) } })
                }
              />
              years' experience
            </label>
          </div>
          <ChipInput
            label="Skip descriptions containing"
            noun="description word"
            chips={eligibility.extra_text_block}
            placeholder="e.g. active clearance"
            onChange={(extra_text_block) =>
              onChange({ eligibility: { ...eligibility, extra_text_block } })
            }
          />
        </div>
      </TileSection>
    </div>
  );
}
