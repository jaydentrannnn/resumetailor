import type { GoalBannerOptions } from "../../../api";
import { OptionChoice, OptionColumns, OptionField, OptionGroup, ShowParts } from "./OptionControls";

/**
 * The weekly-goal banner's options: the goal and what counts, the week and style, then
 * the parts shown — one column each in the customize dialog.
 */
export function GoalOptions({
  goal,
  options,
  onGoal,
  onChange,
  columns = false,
}: {
  goal: number;
  options: GoalBannerOptions;
  onGoal: (goal: number) => void;
  onChange: (patch: Partial<GoalBannerOptions>) => void;
  columns?: boolean;
}) {
  return (
    <OptionColumns columns={columns}>
      <OptionGroup>
        <OptionField label="Goal a week">
          <input
            aria-label="Goal a week"
            className="field w-28"
            type="number"
            min={1}
            max={500}
            value={goal}
            onChange={(e) => onGoal(Math.min(500, Math.max(1, Number(e.target.value) || 1)))}
          />
        </OptionField>
        <OptionChoice
          label="What counts"
          items={[
            { id: "sent", label: "Sent" },
            { id: "autofilled", label: "Autofilled" },
            { id: "tailored", label: "Tailored" },
          ]}
          value={options.counts}
          onChange={(counts) => onChange({ counts })}
        />
      </OptionGroup>
      <OptionGroup>
        <OptionChoice
          label="Week starts on"
          items={[
            { id: "monday", label: "Monday" },
            { id: "sunday", label: "Sunday" },
          ]}
          value={options.week_start}
          onChange={(week_start) => onChange({ week_start })}
        />
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
        <ShowParts
          items={[
            {
              label: "Day boxes",
              checked: options.show_days,
              disabled: options.compact,
              onChange: (show_days) => onChange({ show_days }),
            },
            {
              label: "Nudge line",
              checked: options.show_nudge,
              onChange: (show_nudge) => onChange({ show_nudge }),
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
