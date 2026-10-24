import { useState, type DragEvent } from "react";
import type { HiringProgress, TrackerCard } from "../../api";
import { RowActionsMenu, type MenuItem } from "../../components/TableControls";
import { StatusChip, type Tone } from "../../components/ui";
import { hiringTone } from "../../lib/applicationStatus";
import { COLUMN_LABELS, initials, moveTargets, shortDate } from "../../lib/tracker";
import { CardEmail, PendingEmailConfirm } from "./CardEmail";
import { useTracker } from "./trackerContext";

/** The hiring chip's tone: the Done table's (`hiringTone`); never-sent reads muted. */
function tone(card: TrackerCard): Tone {
  if (card.column === "not_sent") return "muted";
  return hiringTone({
    stage: card.stage as HiringProgress["stage"],
    closed: card.closed as HiringProgress["closed"],
    responded: false,
    stage_dates: card.stage_dates,
    label: card.label,
  });
}

/**
 * One application on the board. Sent cards drag to another column (or use the ⋯ menu,
 * the keyboard and touch path); a tray email dropped here asks before recording.
 */
export function TrackerCardView({
  card,
  onClose,
}: {
  card: TrackerCard;
  /** Ask why it closed (the column's reason chooser), for the menu's "Closed". */
  onClose: (card: TrackerCard) => void;
}) {
  const tracker = useTracker();
  const [over, setOver] = useState(false);
  const draggable = card.column !== "not_sent";
  const takesEmail = tracker.drag?.kind === "email";
  const pending = tracker.pendingEmail?.cardId === card.id ? tracker.pendingEmail : null;

  const items: MenuItem[] = [
    ...moveTargets(card)
      .filter((id) => id !== card.column || id === "closed")
      .map((id) => ({
        label:
          id === "closed"
            ? card.column === "closed"
              ? "Change why it closed…"
              : "Closed…"
            : `Move to ${COLUMN_LABELS[id]}`,
        action: () => (id === "closed" ? onClose(card) : void tracker.move(card, id)),
      })),
    { label: "Open application", action: () => tracker.open(card) },
  ];

  const dropProps = takesEmail
    ? {
        onDragOver: (e: DragEvent) => {
          e.preventDefault();
          e.dataTransfer.dropEffect = "move";
          setOver(true);
        },
        onDragLeave: (e: DragEvent) => {
          if (!e.currentTarget.contains(e.relatedTarget as Node | null)) setOver(false);
        },
        onDrop: (e: DragEvent) => {
          e.preventDefault();
          e.stopPropagation();
          setOver(false);
          if (tracker.drag?.kind === "email") {
            tracker.setPendingEmail({ cardId: card.id, proposal: tracker.drag.proposal });
          }
          tracker.setDrag(null);
        },
      }
    : {};

  return (
    <li
      data-tracker-card={card.id}
      draggable={draggable}
      aria-label={`${card.company}, ${card.role}: ${card.label}`}
      onDragStart={(e) => {
        e.dataTransfer.effectAllowed = "move";
        e.dataTransfer.setData("text/plain", card.id);
        tracker.setDrag({ kind: "card", card });
      }}
      onDragEnd={() => tracker.setDrag(null)}
      {...dropProps}
      className={`space-y-2 rounded-sm border bg-paper p-2.5 text-[13px] shadow-[0_1px_0_var(--color-line)] ${
        over ? "border-accent ring-2 ring-accent" : "border-line"
      } ${draggable ? "cursor-grab active:cursor-grabbing" : ""} ${
        tracker.busy === card.id ? "opacity-60" : ""
      }`}
    >
      <div className="flex items-start gap-2.5">
        <span
          aria-hidden
          className="flex size-8 shrink-0 items-center justify-center rounded-sm bg-sunken font-mono text-[11px] font-semibold text-ink-2"
        >
          {initials(card.company)}
        </span>
        <div className="min-w-0 flex-1">
          <button
            type="button"
            className="line-clamp-2 block w-full text-left font-medium leading-snug text-ink hover:underline"
            title={card.role}
            onClick={() => tracker.open(card)}
          >
            {card.role}
          </button>
          <p className="truncate text-xs text-ink-2">{card.company}</p>
          {card.location && <p className="truncate text-xs text-ink-muted">{card.location}</p>}
        </div>
        {draggable && <RowActionsMenu label={`Actions for ${card.company}`} items={items} />}
      </div>
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
        <StatusChip tone={tone(card)}>{card.label}</StatusChip>
        {card.reached && <span className="text-xs text-ink-muted">reached {card.reached}</span>}
        <span className="ml-auto text-xs text-ink-muted">
          {card.column === "not_sent"
            ? "Restore on the Apply page"
            : card.sent_on && `Sent ${shortDate(card.sent_on)}`}
        </span>
      </div>
      {pending && <PendingEmailConfirm card={card} proposal={pending.proposal} />}
      {card.proposals.map((proposal) => (
        <CardEmail key={proposal.id} proposal={proposal} />
      ))}
    </li>
  );
}
