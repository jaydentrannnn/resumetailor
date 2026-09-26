import { useState } from "react";
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
      <div
        role="radiogroup"
        aria-label={ariaLabel}
        className="grid grid-cols-3 gap-1 rounded-md border border-line p-1"
      >
        {PRESETS.map(([choice, label]) => (
          <button
            key={choice}
            type="button"
            role="radio"
            aria-checked={selected === choice}
            onClick={() => pick(choice)}
            className={`min-h-9 rounded px-2 text-sm ${selected === choice ? "bg-accent text-on-accent" : "text-ink-muted hover:text-ink"}`}
          >
            {label}
          </button>
        ))}
      </div>
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
