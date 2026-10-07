import { useState } from "react";

const OTHER = "__other__";

/**
 * A select over a fixed list with a blank ("skip") choice, an optional "Decline to
 * answer" choice (stored as `decline`, which forms resolve to their own decline option),
 * and "Other…" revealing a text box. A stored value outside the list opens as Other, so
 * an older free-text answer is kept and shown rather than lost.
 */
export function ChoiceOrOther({
  id,
  label,
  value,
  onChange,
  options,
  blankLabel = "Skip this question",
  allowDecline = true,
  invalid = false,
}: {
  id: string;
  label: string;
  value: string;
  onChange: (next: string) => void;
  options: string[];
  blankLabel?: string;
  allowDecline?: boolean;
  invalid?: boolean;
}) {
  const known = (text: string) =>
    options.find((option) => option.toLowerCase() === text.toLowerCase());
  const isDecline = allowDecline && value === "decline";
  // Derived, not frozen at mount: the option list can arrive after the first render.
  const [pickedOther, setPickedOther] = useState(false);
  const other = pickedOther || (!!value && !isDecline && !known(value));
  const selected = other ? OTHER : isDecline ? "decline" : (known(value) ?? "");
  return (
    <>
      <select
        id={id}
        aria-label={label}
        aria-invalid={invalid || undefined}
        className="field mt-1"
        value={selected}
        onChange={(e) => {
          const next = e.target.value;
          setPickedOther(next === OTHER);
          onChange(next === OTHER ? "" : next);
        }}
      >
        <option value="">{blankLabel}</option>
        {options.map((option) => (
          <option key={option} value={option}>
            {option}
          </option>
        ))}
        {allowDecline && <option value="decline">Decline to answer</option>}
        <option value={OTHER}>Other…</option>
      </select>
      {other && (
        <input
          aria-label={`${label}, other`}
          className="field mt-2"
          placeholder="Type your answer"
          value={value}
          onChange={(e) => onChange(e.target.value)}
        />
      )}
    </>
  );
}
