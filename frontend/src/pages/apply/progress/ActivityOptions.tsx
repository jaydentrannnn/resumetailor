import type { ActivityBannerOptions } from "../../../api";
import {
  DateRangeFields,
  OptionChoice,
  OptionColumns,
  OptionGroup,
  OptionSelect,
  ShowParts,
} from "./OptionControls";

/**
 * The activity heatmap's options: dates and style, what counts, then the parts shown —
 * one column each in the customize dialog. The heatmap always uses the accent color.
 */
export function ActivityOptions({
  options,
  onChange,
  columns = false,
}: {
  options: ActivityBannerOptions;
  onChange: (patch: Partial<ActivityBannerOptions>) => void;
  columns?: boolean;
}) {
  return (
    <OptionColumns columns={columns}>
      <OptionGroup>
        <OptionSelect
          label="Dates"
          items={[
            { id: "4w", label: "Last 4 weeks" },
            { id: "13w", label: "Last 13 weeks" },
            { id: "26w", label: "Last 26 weeks" },
            { id: "52w", label: "Last 52 weeks" },
            { id: "custom", label: "Custom dates" },
          ]}
          value={options.range}
          onChange={(range) => onChange({ range })}
        />
        {options.range === "custom" && (
          <DateRangeFields start={options.start} end={options.end} onChange={onChange} />
        )}
        <OptionChoice
          label="Style"
          items={[
            { id: "full", label: "Full" },
            { id: "compact", label: "Compact" },
          ]}
          value={options.compact ? "compact" : "full"}
          onChange={(style) => onChange({ compact: style === "compact" })}
        />
      </OptionGroup>
      <OptionGroup>
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
      </OptionGroup>
      <OptionGroup>
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
      </OptionGroup>
    </OptionColumns>
  );
}
