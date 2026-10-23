import type { PayField } from "../api";

/** Each importable field and its label, required ones first. */
export const FIELD_LABELS: [PayField, string][] = [
  ["role", "Role or title"],
  ["currency", "Currency"],
  ["period", "Pay period"],
  ["low", "Low"],
  ["high", "High"],
  ["median", "Median"],
  ["company", "Company"],
  ["level", "Level"],
  ["location", "Location"],
  ["sample_size", "Sample size"],
  ["source", "Source (per row)"],
  ["as_of", "As of (per row)"],
];

/** What the mapping still lacks before an import can work, or "" when it is complete. */
export function missingColumns(mapping: Record<PayField, string>): string {
  const needs = (["role", "currency", "period"] as PayField[]).filter((key) => !mapping[key]);
  const pay = mapping.median || (mapping.low && mapping.high);
  const names = needs.map((key) => FIELD_LABELS.find(([k]) => k === key)![1].toLowerCase());
  if (!pay) names.push("a low and high, or a median");
  return names.length ? `Pick a column for ${names.join(", ")}.` : "";
}
