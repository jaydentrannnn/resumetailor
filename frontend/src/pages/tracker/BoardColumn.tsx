import { useEffect, useState, type DragEvent } from "react";
import type { TrackerCard, TrackerColumn } from "../../api";
import { Button } from "../../components/ui";
import { COLUMN_LABELS, REASON_LABELS, closeReasons } from "../../lib/tracker";
import { TrackerCardView } from "./TrackerCardView";
import { useTracker } from "./trackerContext";

const PAGE = 50;

/** Eye-with-slash: hide this column. */
const HIDE_ICON =
  "M2 8s2.2-4 6-4 6 4 6 4-2.2 4-6 4-6-4-6-4ZM6.5 8a1.5 1.5 0 1 0 3 0a1.5 1.5 0 1 0-3 0M3 13 13 3";

/**
 * One board column. A sent card dragged from another column drops here; dropping on
 * Closed first asks why it closed (Escape keeps the card where it was).
 */
export function BoardColumn({
  column,
  cards,
  asking,
  onAsk,
  onHide,
}: {
  column: TrackerColumn;
  cards: TrackerCard[];
  /** The card waiting for a closing reason (Closed column only). */
  asking: TrackerCard | null;
  onAsk: (card: TrackerCard | null) => void;
  onHide: () => void;
}) {
  const tracker = useTracker();
  const [shown, setShown] = useState(PAGE);
  const [over, setOver] = useState(false);
  const dragged = tracker.drag?.kind === "card" ? tracker.drag.card : null;
  const accepts =
    !!dragged && column !== "not_sent" && (dragged.column !== column || column === "closed");

  useEffect(() => {
    if (!asking) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onAsk(null);
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [asking, onAsk]);

  const drop = {
    onDragOver: (e: DragEvent) => {
      if (!accepts) return;
      e.preventDefault();
      e.dataTransfer.dropEffect = "move";
      setOver(true);
    },
    onDragLeave: (e: DragEvent) => {
      if (!e.currentTarget.contains(e.relatedTarget as Node | null)) setOver(false);
    },
    onDrop: (e: DragEvent) => {
      e.preventDefault();
      setOver(false);
      tracker.setDrag(null);
      if (!dragged || !accepts) return;
      if (column === "closed") onAsk(dragged);
      else void tracker.move(dragged, column);
    },
  };

  return (
    <section
      aria-label={`${COLUMN_LABELS[column]}, ${cards.length}`}
      data-tracker-column={column}
      {...drop}
      className={`flex min-w-[15rem] max-w-[22rem] flex-1 basis-0 flex-col rounded-md border bg-sunken/60 ${
        over ? "border-accent ring-2 ring-accent" : accepts ? "border-accent/40" : "border-line"
      }`}
    >
      <header className="flex items-center gap-2 px-3 pb-2 pt-2.5">
        <h2 className="text-xs font-semibold uppercase tracking-wide text-ink-2">
          {COLUMN_LABELS[column]}
        </h2>
        <span className="font-mono text-xs text-ink-muted">{cards.length}</span>
        <span className="flex-1" />
        <button
          type="button"
          aria-label={`Hide ${COLUMN_LABELS[column]}`}
          title={`Hide ${COLUMN_LABELS[column]}`}
          onClick={onHide}
          className="rt-row-action inline-flex size-6 min-h-0 items-center justify-center rounded-sm text-ink-muted hover:bg-plain-hover hover:text-ink"
        >
          <svg
            aria-hidden
            viewBox="0 0 16 16"
            className="size-3.5"
            fill="none"
            stroke="currentColor"
            strokeWidth={1.4}
          >
            <path d={HIDE_ICON} />
          </svg>
        </button>
      </header>
      {asking && (
        <div
          role="group"
          aria-label={`Why did ${asking.company} close?`}
          className="mx-2 mb-2 space-y-1.5 rounded-sm border border-accent bg-paper p-2 text-xs"
        >
          <p className="text-ink-2">Why did {asking.company} close?</p>
          <div className="flex flex-wrap gap-1.5">
            {closeReasons(asking).map((reason) => (
              <Button
                key={reason}
                size="sm"
                variant="secondary"
                onClick={() => {
                  onAsk(null);
                  void tracker.move(asking, "closed", reason);
                }}
              >
                {REASON_LABELS[reason]}
              </Button>
            ))}
            <Button size="sm" variant="ghost" onClick={() => onAsk(null)}>
              Cancel
            </Button>
          </div>
        </div>
      )}
      <ul className="flex min-h-24 flex-col gap-2 px-2 pb-2">
        {cards.slice(0, shown).map((card) => (
          <TrackerCardView key={card.id} card={card} onClose={onAsk} />
        ))}
        {cards.length === 0 && (
          <li className="px-1 py-6 text-center text-xs text-ink-muted">
            {accepts ? "Drop here" : "Nothing here"}
          </li>
        )}
      </ul>
      {cards.length > shown && (
        <div className="px-2 pb-2">
          <Button
            size="sm"
            variant="ghost"
            className="w-full"
            onClick={() => setShown((n) => n + PAGE)}
          >
            Show {Math.min(PAGE, cards.length - shown)} more
          </Button>
        </div>
      )}
    </section>
  );
}
