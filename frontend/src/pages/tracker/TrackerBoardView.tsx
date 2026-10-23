import { useState } from "react";
import type { TrackerCard, TrackerColumn } from "../../api";
import { TRACKER_COLUMNS, byColumn } from "../../lib/tracker";
import { BoardColumn } from "./BoardColumn";

/**
 * The columns side by side, scrolling sideways on a narrow window. The Closed column's
 * reason chooser is board state, so the card menu's "Closed…" can open it too (and a
 * hidden Closed column shows while it asks).
 */
export function TrackerBoardView({
  cards,
  hidden,
  onHide,
}: {
  cards: TrackerCard[];
  hidden: TrackerColumn[];
  onHide: (column: TrackerColumn) => void;
}) {
  const [asking, setAsking] = useState<TrackerCard | null>(null);
  const columns = byColumn(cards);
  const visible = TRACKER_COLUMNS.filter(
    (c) => !hidden.includes(c.id) || (c.id === "closed" && asking),
  );
  return (
    <div className="overflow-x-auto pb-2">
      <div className="flex items-start gap-3">
        {visible.map(({ id }) => (
          <BoardColumn
            key={id}
            column={id}
            cards={columns[id]}
            asking={id === "closed" ? asking : null}
            onAsk={setAsking}
            onHide={() => onHide(id)}
          />
        ))}
      </div>
    </div>
  );
}
