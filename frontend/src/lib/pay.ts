import type { PayCurrency, PayPeriod } from "../api";

const PER: Record<PayPeriod, string> = {
  hour: "an hour",
  week: "a week",
  month: "a month",
  year: "a year",
};

/** "$22.50", "CA$70,000", "£2,625": cents only when the figure has them. */
export function money(value: number, currency: PayCurrency): string {
  const cents = !Number.isInteger(value);
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency,
    minimumFractionDigits: cents ? 2 : 0,
    maximumFractionDigits: cents ? 2 : 0,
  }).format(value);
}

/** "$25–$30 an hour", or "$27 an hour" for a single figure. */
export function payRange(
  low: number,
  high: number,
  currency: PayCurrency,
  period: PayPeriod,
): string {
  const figures =
    low === high ? money(low, currency) : `${money(low, currency)}–${money(high, currency)}`;
  return `${figures} ${PER[period]}`;
}

/** "USD, an hour": the heading of one currency/period split. */
export const splitHeading = (currency: PayCurrency, period: PayPeriod) =>
  `${currency}, ${PER[period]}`;

/** "Sep 2026" or "Aug – Sep 2026" for a group's posting dates. */
export function dateSpan(first: string, last: string): string {
  if (!first) return "";
  const fmt = (iso: string, year: boolean) =>
    new Date(`${iso.slice(0, 10)}T00:00:00`).toLocaleDateString("en-US", {
      month: "short",
      ...(year ? { year: "numeric" } : {}),
    });
  if (first.slice(0, 7) === last.slice(0, 7)) return fmt(first, true);
  const sameYear = first.slice(0, 4) === last.slice(0, 4);
  return `${fmt(first, !sameYear)} – ${fmt(last, true)}`;
}
