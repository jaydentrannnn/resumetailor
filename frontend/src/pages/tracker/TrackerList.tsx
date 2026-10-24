import { useState } from "react";
import type { TrackerCard, TrackerColumn, TrackerReason } from "../../api";
import {
  COLUMN_LABELS,
  REASON_LABELS,
  TRACKER_COLUMNS,
  closeReasons,
  moveTargets,
  shortDate,
} from "../../lib/tracker";
import { useTracker } from "./trackerContext";

type SortKey = "company" | "role" | "column" | "sent_on" | "last_update";
const HEADERS: [SortKey | null, string][] = [
  ["company", "Company"],
  ["role", "Role"],
  ["column", "Stage"],
  ["sent_on", "Sent on"],
  ["last_update", "Last update"],
  [null, "Email"],
];

/** The Stage select: a step column, or "closed:<reason>". */
function StageSelect({ card }: { card: TrackerCard }) {
  const tracker = useTracker();
  if (card.column === "not_sent") return <span className="text-ink-muted">{card.label}</span>;
  const value = card.column === "closed" ? `closed:${card.closed}` : card.column;
  const reasons = [...closeReasons(card), ...(card.closed ? [card.closed as TrackerReason] : [])];
  return (
    <select
      aria-label={`Stage of ${card.company}`}
      className="field w-auto py-0 text-xs"
      value={value}
      disabled={tracker.busy === card.id}
      onChange={(e) => {
        const [column, reason] = e.target.value.split(":") as [TrackerColumn, TrackerReason?];
        void tracker.move(card, column, reason);
      }}
    >
      {moveTargets(card)
        .filter((id) => id !== "closed")
        .map((id) => (
          <option key={id} value={id}>
            {COLUMN_LABELS[id]}
          </option>
        ))}
      {reasons.map((reason) => (
        <option key={reason} value={`closed:${reason}`}>
          Closed: {REASON_LABELS[reason]}
        </option>
      ))}
    </select>
  );
}

/** The same cards as a sortable table; the Stage select moves a card like a drag. */
export function TrackerList({ cards }: { cards: TrackerCard[] }) {
  const tracker = useTracker();
  const [sort, setSort] = useState<{ key: SortKey; down: boolean }>({
    key: "last_update",
    down: true,
  });
  const value = (card: TrackerCard) =>
    sort.key === "column"
      ? String(TRACKER_COLUMNS.findIndex((c) => c.id === card.column))
      : String(card[sort.key] ?? "").toLowerCase();
  const rows = [...cards].sort((a, b) => {
    const x = value(a);
    const y = value(b);
    return (x < y ? -1 : x > y ? 1 : 0) * (sort.down ? -1 : 1);
  });
  return (
    <div className="overflow-x-auto rounded-md border border-line">
      <table className="w-full min-w-[44rem] text-left text-[13px]">
        <thead className="bg-panel text-xs text-ink-2">
          <tr>
            {HEADERS.map(([key, label]) => (
              <th
                key={label}
                className="px-3 py-2 font-medium"
                aria-sort={
                  key && sort.key === key ? (sort.down ? "descending" : "ascending") : undefined
                }
              >
                {key ? (
                  <button
                    type="button"
                    className="hover:text-ink"
                    onClick={() => setSort((s) => ({ key, down: s.key === key ? !s.down : false }))}
                  >
                    {label}
                    {sort.key === key ? (sort.down ? " ↓" : " ↑") : ""}
                  </button>
                ) : (
                  label
                )}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((card) => (
            <tr key={card.id} className="border-t border-line">
              <td className="px-3 py-2 font-medium text-ink">{card.company}</td>
              <td className="max-w-72 truncate px-3 py-2">
                <button
                  type="button"
                  className="truncate hover:underline"
                  onClick={() => tracker.open(card)}
                >
                  {card.role}
                </button>
              </td>
              <td className="px-3 py-2">
                <StageSelect card={card} />
              </td>
              <td className="px-3 py-2 text-ink-muted">{shortDate(card.sent_on)}</td>
              <td className="px-3 py-2 text-ink-muted">{shortDate(card.last_update)}</td>
              <td className="px-3 py-2 text-ink-muted">
                {card.proposals.length ? `${card.proposals.length} to review` : ""}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
