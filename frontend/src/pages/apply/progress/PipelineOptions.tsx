import type { PipelineBannerOptions, PipelineStage } from "../../../api";
import { STAGE_LABELS, STAGE_ORDER } from "../../../lib/progressOptions";
import { DateRangeFields, OptionChoice, OptionField, ShowParts } from "./OptionControls";

/** The pipeline's options: which postings (by when found), stages, style and parts. */
export function PipelineOptions({
  options,
  onChange,
}: {
  options: PipelineBannerOptions;
  onChange: (patch: Partial<PipelineBannerOptions>) => void;
}) {
  function toggleStage(stage: PipelineStage, on: boolean) {
    const next = on ? [...options.stages, stage] : options.stages.filter((s) => s !== stage);
    onChange({ stages: STAGE_ORDER.filter((s) => next.includes(s)) });
  }
  return (
    <div className="space-y-4">
      <OptionChoice
        label="Postings found"
        items={[
          { id: "all", label: "All time" },
          { id: "week", label: "This week" },
          { id: "month", label: "This month" },
          { id: "30d", label: "Last 30 days" },
          { id: "custom", label: "Custom" },
        ]}
        value={options.range}
        onChange={(range) => onChange({ range })}
      />
      {options.range === "custom" && (
        <DateRangeFields start={options.start} end={options.end} onChange={onChange} />
      )}
      <OptionField label="Stages (at least two)">
        <div className="flex flex-wrap gap-x-5 gap-y-2">
          {STAGE_ORDER.map((stage) => {
            const checked = options.stages.includes(stage);
            return (
              <label key={stage} className="flex items-center gap-2 text-sm">
                <input
                  type="checkbox"
                  className="h-4 w-4 accent-[var(--color-accent)]"
                  checked={checked}
                  disabled={checked && options.stages.length <= 2}
                  onChange={(e) => toggleStage(stage, e.target.checked)}
                />
                {STAGE_LABELS[stage]}
              </label>
            );
          })}
        </div>
      </OptionField>
      <OptionChoice
        label="Style"
        items={[
          { id: "cards", label: "Cards" },
          { id: "funnel", label: "Funnel" },
          { id: "compact", label: "Compact" },
        ]}
        value={options.style}
        onChange={(style) => onChange({ style })}
      />
      <ShowParts
        items={[
          {
            label: "Percentages",
            checked: options.show_percent,
            onChange: (show_percent) => onChange({ show_percent }),
          },
          {
            label: "Biggest drop",
            checked: options.show_drop,
            disabled: options.style === "compact",
            onChange: (show_drop) => onChange({ show_drop }),
          },
          {
            label: "Action buttons",
            checked: options.show_actions,
            onChange: (show_actions) => onChange({ show_actions }),
          },
        ]}
      />
    </div>
  );
}
