/**
 * Dates the Profile page edits as a month select plus typed year (and day): stored as
 * `YYYY-MM-DD`, `YYYY-MM` or `YYYY`, the shapes the backend (`content/dates.py`) reads.
 * Free text that names no date ("Present", "Fall 2022") is carried through untouched.
 */

export const MONTH_NAMES = [
  "January",
  "February",
  "March",
  "April",
  "May",
  "June",
  "July",
  "August",
  "September",
  "October",
  "November",
  "December",
] as const;

export type DatePrecision = "month" | "day";

export type DateParts = { year: string; month: string; day: string };

export const EMPTY_PARTS: DateParts = { year: "", month: "", day: "" };

/** The month/year/day a stored value states, or null when it is not a date. */
export function parseDate(value: string | undefined | null): DateParts | null {
  const match = /^(\d{4})(?:-(\d{2})(?:-(\d{2}))?)?$/.exec((value ?? "").trim());
  if (!match) return null;
  return { year: match[1], month: match[2] ? String(Number(match[2])) : "", day: match[3] ?? "" };
}

function daysIn(year: number, month: number): number {
  return new Date(year, month, 0).getDate();
}

/**
 * The stored value for the typed parts, or null while they are incomplete or impossible
 * (no month, a year that is not four digits, February 30th). `month` precision ignores
 * the day.
 */
export function composeDate(parts: DateParts, precision: DatePrecision): string | null {
  if (!/^\d{4}$/.test(parts.year) || !parts.month) return null;
  const year = Number(parts.year);
  const month = Number(parts.month);
  if (year < 1950 || year > 2100 || month < 1 || month > 12) return null;
  const mm = String(month).padStart(2, "0");
  if (precision === "month") return `${parts.year}-${mm}`;
  const day = Number(parts.day);
  if (!/^\d{1,2}$/.test(parts.day) || day < 1 || day > daysIn(year, month)) return null;
  return `${parts.year}-${mm}-${String(day).padStart(2, "0")}`;
}

/** "June 2027" / "June 14, 2027" for a stored value; free text comes back as written. */
export function displayDate(value: string | undefined | null): string {
  const text = (value ?? "").trim();
  const parts = parseDate(text);
  if (!parts) return text;
  if (!parts.month) return parts.year;
  const month = MONTH_NAMES[Number(parts.month) - 1];
  return parts.day ? `${month} ${Number(parts.day)}, ${parts.year}` : `${month} ${parts.year}`;
}

/** Why the typed parts are not a date yet, or null when they are blank or complete. */
export function dateProblem(parts: DateParts, precision: DatePrecision): string | null {
  const blank = !parts.year && !parts.month && !parts.day;
  if (blank || composeDate(parts, precision)) return null;
  if (!parts.month) return "Pick a month.";
  if (!/^\d{4}$/.test(parts.year)) return "Enter a 4-digit year.";
  if (precision === "day" && !parts.day) return "Enter the day.";
  return "That date doesn't exist.";
}
