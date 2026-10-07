import { useEffect, useRef, useState } from "react";
import {
  EMPTY_PARTS,
  MONTH_NAMES,
  composeDate,
  dateProblem,
  parseDate,
  type DateParts as Parts,
  type DatePrecision,
} from "../lib/dates";

/**
 * One date as a month select plus a typed year (and a day when `precision="day"`), so
 * every date on the Profile page is entered the same way. Emits `YYYY-MM[-DD]`, `""`
 * while blank or incomplete, or `"Present"` when `allowPresent` is ticked. A stored value
 * that is not a date (older free text) shows as it was written with a way to replace it.
 * `fallback` is what a blank value stands for ("June 2027"), shown inside the controls.
 */
export function DateParts({
  value,
  onChange,
  precision = "month",
  allowPresent = false,
  fallback,
  label,
  id,
  invalid = false,
}: {
  value: string;
  onChange: (next: string) => void;
  precision?: DatePrecision;
  allowPresent?: boolean;
  fallback?: string;
  label: string;
  id?: string;
  invalid?: boolean;
}) {
  const present = allowPresent && value === "Present";
  const parsed = parseDate(value);
  const legacy = !!value && !parsed && !present;
  const [parts, setParts] = useState<Parts>(parsed ?? EMPTY_PARTS);
  const emitted = useRef(value);
  useEffect(() => {
    if (value === emitted.current) return;
    emitted.current = value;
    setParts(parseDate(value) ?? EMPTY_PARTS);
  }, [value]);

  function emit(next: string) {
    emitted.current = next;
    if (next !== value) onChange(next);
  }
  function update(next: Parts) {
    setParts(next);
    const blank = !next.year && !next.month && !next.day;
    emit(blank ? "" : (composeDate(next, precision) ?? ""));
  }
  const problem = dateProblem(parts, precision);
  const fallbackParts = parseDate(fallback ? toIso(fallback) : "");

  if (legacy) {
    return (
      <div role="group" aria-label={label} className="mt-1 flex flex-wrap items-center gap-2">
        <span className="rounded-md border border-line bg-paper/40 px-2 py-1.5 text-sm">
          {value}
        </span>
        <button
          type="button"
          className="text-xs text-accent underline"
          onClick={() => {
            setParts(EMPTY_PARTS);
            emit("");
          }}
        >
          Pick a date instead
        </button>
      </div>
    );
  }
  return (
    <div role="group" aria-label={label} className="mt-1">
      <div className="flex flex-wrap items-center gap-2">
        <select
          id={id}
          aria-label={`${label}, month`}
          aria-invalid={invalid || !!problem || undefined}
          className="field w-40"
          disabled={present}
          value={present ? "" : parts.month}
          onChange={(e) => update({ ...parts, month: e.target.value })}
        >
          <option value="">{fallback ? `From resume (${fallback})` : "Month"}</option>
          {MONTH_NAMES.map((name, index) => (
            <option key={name} value={String(index + 1)}>
              {name}
            </option>
          ))}
        </select>
        <input
          aria-label={`${label}, year`}
          aria-invalid={invalid || !!problem || undefined}
          className="field w-24"
          inputMode="numeric"
          maxLength={4}
          placeholder={fallbackParts?.year || "Year"}
          disabled={present}
          value={present ? "" : parts.year}
          onChange={(e) => update({ ...parts, year: e.target.value.replace(/\D/g, "") })}
        />
        {precision === "day" && (
          <input
            aria-label={`${label}, day`}
            aria-invalid={invalid || !!problem || undefined}
            className="field w-20"
            inputMode="numeric"
            maxLength={2}
            placeholder={fallbackParts?.day || "Day"}
            value={parts.day}
            onChange={(e) => update({ ...parts, day: e.target.value.replace(/\D/g, "") })}
          />
        )}
        {allowPresent && (
          <label className="flex items-center gap-1.5 text-sm">
            <input
              type="checkbox"
              checked={present}
              onChange={(e) => {
                if (e.target.checked) {
                  setParts(EMPTY_PARTS);
                  emit("Present");
                } else emit("");
              }}
            />
            Present
          </label>
        )}
      </div>
      {problem && <span className="mt-1 block text-xs text-danger">{problem}</span>}
    </div>
  );
}

/** "June 2027" -> "2027-06" so a displayed fallback can fill the placeholders. */
function toIso(text: string): string {
  const match = /^([A-Za-z]+)(?:\s+(\d{1,2}),)?\s+(\d{4})$/.exec(text.trim());
  if (!match) return "";
  const month = MONTH_NAMES.findIndex((name) => name.toLowerCase() === match[1].toLowerCase());
  if (month < 0) return "";
  const mm = String(month + 1).padStart(2, "0");
  return match[2] ? `${match[3]}-${mm}-${match[2].padStart(2, "0")}` : `${match[3]}-${mm}`;
}
