import { useState } from "react";
import { Segmented } from "../../components/ui";
import { ageChoice } from "../../lib/applyPage";

const PRESETS: Array<[value: "1" | "7" | "custom", label: string]> = [
  ["1", "1 day"],
  ["7", "7 days"],
  ["custom", "Custom"],
];

/**
 * How old a posting may be: 1 day, 7 days, or a custom count. Shared by the one-off
 * Search options and the saved nightly setting so both read the same.
 */
export function AgeWindowPicker({
  value,
  onChange,
  ariaLabel,
}: {
  value: number;
  onChange: (days: number) => void;
  ariaLabel: string;
}) {
  // Custom stays open even when the typed number happens to be 1 or 7.
  const [custom, setCustom] = useState(ageChoice(value) === "custom");
  const selected = custom ? "custom" : ageChoice(value);

  function pick(choice: "1" | "7" | "custom") {
    setCustom(choice === "custom");
    if (choice !== "custom") onChange(Number(choice));
  }

  return (
    <div className="space-y-2">
      <Segmented
        label={ariaLabel}
        items={PRESETS.map(([id, label]) => ({ id, label }))}
        value={selected}
        onChange={(id) => pick(id as "1" | "7" | "custom")}
      />
      {selected === "custom" && (
        <label className="block">
          Last{" "}
          <input
            className="field mx-1 inline-block w-20"
            type="number"
            min={0}
            max={365}
            aria-label={`${ariaLabel}, custom days`}
            value={value}
            onChange={(e) => onChange(Math.min(365, Math.max(0, Number(e.target.value) || 0)))}
          />{" "}
          day(s)
        </label>
      )}
    </div>
  );
}
