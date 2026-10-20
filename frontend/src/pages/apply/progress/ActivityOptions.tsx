import type { ActivityBannerOptions } from "../../../api";
import { HEAT_COLORS } from "../../../lib/progressOptions";
import { DateRangeFields, OptionChoice, OptionField, ShowParts } from "./OptionControls";

const COLORS: { id: ActivityBannerOptions["color"]; label: string }[] = [
  { id: "green", label: "Green" },
  { id: "blue", label: "Blue" },
  { id: "orange", label: "Orange" },
  { id: "purple", label: "Purple" },
];

/** The activity heatmap's options: dates, what counts, color, style and parts. */
export function ActivityOptions({
  options,
  onChange,
}: {
  options: ActivityBannerOptions;
  onChange: (patch: Partial<ActivityBannerOptions>) => void;
}) {
  return (
    <div className="space-y-4">
      <OptionChoice
        label="Dates"
        items={[
          { id: "4w", label: "4 weeks" },
          { id: "13w", label: "13 weeks" },
          { id: "26w", label: "26 weeks" },
          { id: "52w", label: "52 weeks" },
          { id: "custom", label: "Custom" },
        ]}
        value={options.range}
        onChange={(range) => onChange({ range })}
      />
      {options.range === "custom" && (
        <DateRangeFields start={options.start} end={options.end} onChange={onChange} />
      )}
      <OptionChoice
        label="What counts"
        items={[
          { id: "sent", label: "Sent" },
          { id: "autofilled", label: "Autofilled" },
          { id: "tailored", label: "Tailored" },
          { id: "found", label: "Found" },
        ]}
        value={options.counts}
        onChange={(counts) => onChange({ counts })}
      />
      <OptionField label="Color">
        <div role="radiogroup" aria-label="Color" className="flex flex-wrap gap-2">
          {COLORS.map((color) => (
            <button
              key={color.id}
              type="button"
              role="radio"
              aria-checked={options.color === color.id}
              onClick={() => onChange({ color: color.id })}
              className={`flex items-center gap-2 rounded-sm border px-2.5 py-1.5 text-sm ${
                options.color === color.id ? "border-ink text-ink" : "border-line text-ink-2"
              }`}
            >
              <span
                aria-hidden
                className="size-3.5 rounded-[3px]"
                style={{ background: HEAT_COLORS[color.id] }}
              />
              {color.label}
            </button>
          ))}
        </div>
      </OptionField>
      <OptionChoice
        label="Style"
        items={[
          { id: "full", label: "Full" },
          { id: "compact", label: "Compact" },
        ]}
        value={options.compact ? "compact" : "full"}
        onChange={(style) => onChange({ compact: style === "compact" })}
      />
      <ShowParts
        items={[
          {
            label: "Best and last day",
            checked: options.show_stats,
            onChange: (show_stats) => onChange({ show_stats }),
          },
          {
            label: "What's waiting",
            checked: options.show_waiting,
            disabled: options.compact,
            onChange: (show_waiting) => onChange({ show_waiting }),
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
