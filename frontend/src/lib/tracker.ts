import type { TrackerBoard, TrackerCard, TrackerColumn, TrackerReason } from "../api";

/** Board columns left to right, with their headings. */
export const TRACKER_COLUMNS: { id: TrackerColumn; label: string }[] = [
  { id: "not_sent", label: "Not sent" },
  { id: "applied", label: "Applied" },
  { id: "assessment", label: "Assessment" },
  { id: "interview", label: "Interviewing" },
  { id: "offer", label: "Offer" },
  { id: "closed", label: "Closed" },
];

export const COLUMN_LABELS = Object.fromEntries(
  TRACKER_COLUMNS.map((c) => [c.id, c.label]),
) as Record<TrackerColumn, string>;

export const REASON_LABELS: Record<TrackerReason, string> = {
  rejected: "Rejected",
  ghosted: "No reply",
  withdrawn: "Withdrawn",
  offer_declined: "Offer declined",
};

/** Columns a card can be moved to by hand: never into or out of Not sent. */
export function moveTargets(card: TrackerCard): TrackerColumn[] {
  if (card.column === "not_sent") return [];
  return TRACKER_COLUMNS.map((c) => c.id).filter((id) => id !== "not_sent");
}

/** Reasons offered when a card is dropped on Closed; declining needs an offer. */
export function closeReasons(card: TrackerCard): TrackerReason[] {
  const offered = card.stage === "offer" || card.stage === "hired";
  const all: TrackerReason[] = ["rejected", "ghosted", "withdrawn", "offer_declined"];
  return all.filter((r) => (r !== "offer_declined" || offered) && r !== card.closed);
}

export type TrackerFilters = { q: string; from: string; until: string; email: boolean };

export const NO_FILTERS: TrackerFilters = { q: "", from: "", until: "", email: false };

/** Cards matching the filters; the date range is on the day the application went out. */
export function filterCards(cards: TrackerCard[], f: TrackerFilters): TrackerCard[] {
  const words = f.q.trim().toLowerCase().split(/\s+/).filter(Boolean);
  return cards.filter((card) => {
    const text = `${card.company} ${card.role} ${card.location}`.toLowerCase();
    if (!words.every((w) => text.includes(w))) return false;
    if (f.email && card.proposals.length === 0) return false;
    if (f.from && (!card.sent_on || card.sent_on < f.from)) return false;
    if (f.until && (!card.sent_on || card.sent_on > f.until)) return false;
    return true;
  });
}

/** Cards per column, in board order (most recent update first, as the server sorts). */
export function byColumn(cards: TrackerCard[]): Record<TrackerColumn, TrackerCard[]> {
  const out = Object.fromEntries(TRACKER_COLUMNS.map((c) => [c.id, []])) as unknown as Record<
    TrackerColumn,
    TrackerCard[]
  >;
  for (const card of cards) out[card.column].push(card);
  return out;
}

/** The board with one card replaced (a move's result, or a rollback). */
export function withCard(board: TrackerBoard, card: Omit<TrackerCard, "proposals">): TrackerBoard {
  const cards = board.cards.map((c) => (c.id === card.id ? { ...c, ...card } : c));
  const counts = Object.fromEntries(TRACKER_COLUMNS.map((c) => [c.id, 0])) as Record<
    TrackerColumn,
    number
  >;
  for (const c of cards) counts[c.column] += 1;
  return { ...board, cards, counts };
}

/** The card as it shows the moment it is dropped, before the server answers. */
export function optimistic(
  card: TrackerCard,
  column: TrackerColumn,
  reason?: TrackerReason,
): TrackerCard {
  if (column === "closed") {
    const reached =
      card.column === "closed"
        ? card.reached
        : card.column === "applied"
          ? ""
          : COLUMN_LABELS[card.column];
    return {
      ...card,
      column,
      closed: reason ?? null,
      label: reason ? REASON_LABELS[reason] : "",
      reached,
    };
  }
  return { ...card, column, closed: null, reached: "", label: COLUMN_LABELS[column] };
}

const HIDDEN_KEY = "rt.tracker.hidden.";
const SEEN_KEY = "rt.tracker.autoSeen.";

/** Automatic closes this browser was told about ("Got it"), so the notice shows only new ones. */
export function readSeenAuto(workspaceId: string): string[] {
  try {
    const raw = window.localStorage.getItem(SEEN_KEY + workspaceId);
    if (raw) return JSON.parse(raw) as string[];
  } catch {
    // storage blocked or malformed: show them all
  }
  return [];
}

export function writeSeenAuto(workspaceId: string, ids: string[]): void {
  try {
    window.localStorage.setItem(SEEN_KEY + workspaceId, JSON.stringify(ids.slice(-200)));
  } catch {
    // advisory only
  }
}

/** Columns hidden on this browser; Not sent starts hidden. */
export function readHidden(workspaceId: string): TrackerColumn[] {
  try {
    const raw = window.localStorage.getItem(HIDDEN_KEY + workspaceId);
    if (raw) return JSON.parse(raw) as TrackerColumn[];
  } catch {
    // storage blocked or malformed: fall back to the default
  }
  return ["not_sent"];
}

export function writeHidden(workspaceId: string, hidden: TrackerColumn[]): void {
  try {
    window.localStorage.setItem(HIDDEN_KEY + workspaceId, JSON.stringify(hidden));
  } catch {
    // advisory only
  }
}

/** "Oct 20" for this year, "Oct 20, 2025" otherwise; "" when unknown. */
export function shortDate(iso: string | null | undefined, today = new Date()): string {
  if (!iso) return "";
  const day = new Date(`${iso.slice(0, 10)}T00:00:00`);
  if (Number.isNaN(day.getTime())) return "";
  const sameYear = day.getFullYear() === today.getFullYear();
  return day.toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    ...(sameYear ? {} : { year: "numeric" }),
  });
}

/** Up to two letters for the card's company mark. */
export function initials(company: string): string {
  const words = company
    .replace(/[^\p{L}\p{N} ]/gu, " ")
    .split(/\s+/)
    .filter(Boolean);
  return (
    words.length > 1 ? words[0][0] + words[1][0] : (words[0] ?? "?").slice(0, 2)
  ).toUpperCase();
}
