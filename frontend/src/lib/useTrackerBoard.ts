import { useCallback, useEffect, useRef, useState } from "react";
import {
  acceptMailProposal,
  checkMailNow,
  dismissMailProposal,
  getTrackerBoard,
  moveTrackerCard,
  undoMailProposal,
  undoTrackerMove,
  type MailProposal,
  type TrackerBoard,
  type TrackerCard,
  type TrackerColumn,
  type TrackerReason,
} from "../api";
import { startAdaptivePoll } from "./adaptivePoll";
import { describe } from "./errors";
import { useToast } from "./toast";
import { COLUMN_LABELS, REASON_LABELS, optimistic, withCard } from "./tracker";

/**
 * The Tracker board's data and every change to it. The board polls (an email update
 * Claude Desktop posts shows up without a reload); a poll that overlaps a change is
 * dropped, so it cannot put back the card the student just moved.
 */
export function useTrackerBoard() {
  const toast = useToast();
  const [board, setBoard] = useState<TrackerBoard | null>(null);
  const [loadError, setLoadError] = useState<unknown>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const inFlight = useRef(0);
  // Bumped when a change starts or ends: a poll begun before it is out of date.
  const generation = useRef(0);
  const poll = useRef<{ wake: () => void } | null>(null);

  useEffect(() => {
    const handle = startAdaptivePoll(async () => {
      try {
        const asked = generation.current;
        const next = await getTrackerBoard();
        setLoadError(null);
        // Dropped: ask again soon (the busy pace), since a wake during it was skipped.
        if (inFlight.current > 0 || asked !== generation.current) return true;
        setBoard(next);
      } catch (reason) {
        setLoadError(reason);
      }
      return false;
    });
    poll.current = handle;
    return () => handle.stop();
  }, []);

  const change = useCallback(async <T>(key: string, work: () => Promise<T>) => {
    inFlight.current += 1;
    generation.current += 1;
    setBusy(key);
    try {
      return await work();
    } finally {
      inFlight.current -= 1;
      generation.current += 1;
      setBusy(null);
      poll.current?.wake();
    }
  }, []);

  const undo = useCallback(
    (card: TrackerCard, receipt: { added: string[]; voided: string[] }) =>
      void change(card.id, async () => {
        try {
          const back = await undoTrackerMove(card.id, receipt);
          setBoard((b) => (b ? withCard(b, back) : b));
          toast.success(`Back in ${COLUMN_LABELS[back.column]}`);
        } catch (reason) {
          toast.error("Could not undo", describe(reason).detail);
        }
      }),
    [change, toast],
  );

  const move = useCallback(
    (card: TrackerCard, column: TrackerColumn, reason?: TrackerReason) =>
      change(card.id, async () => {
        setBoard((b) => (b ? withCard(b, optimistic(card, column, reason)) : b));
        try {
          const { card: moved, receipt } = await moveTrackerCard(card.id, column, reason);
          setBoard((b) => (b ? withCard(b, moved) : b));
          const where = reason ? `Closed: ${REASON_LABELS[reason]}` : `Moved to ${COLUMN_LABELS[column]}`;
          if (receipt.added.length || receipt.voided.length) {
            toast.success(`${card.company}: ${where}`, undefined, {
              label: "Undo",
              onClick: () => undo(moved as TrackerCard, receipt),
            });
          }
        } catch (reason) {
          setBoard((b) => (b ? withCard(b, card) : b));
          toast.error(`Could not move ${card.company}`, describe(reason).detail);
        }
      }),
    [change, toast, undo],
  );

  const acceptEmail = useCallback(
    (proposal: MailProposal, appId?: string) =>
      change(proposal.id, async () => {
        try {
          await acceptMailProposal(proposal.id, appId ? { app_id: appId } : {});
          toast.success("Recorded from email");
        } catch (reason) {
          toast.error("Could not record that email", describe(reason).detail);
        }
      }),
    [change, toast],
  );

  const dismissEmail = useCallback(
    (proposal: MailProposal) =>
      change(proposal.id, async () => {
        try {
          await dismissMailProposal(proposal.id);
        } catch (reason) {
          toast.error("Could not dismiss that email", describe(reason).detail);
        }
      }),
    [change, toast],
  );

  const undoAutoClose = useCallback(
    (proposal: MailProposal) =>
      change(proposal.id, async () => {
        try {
          await undoMailProposal(proposal.id);
          toast.success(`${proposal.company || "Application"}: reopened`);
        } catch (reason) {
          toast.error("Could not undo that close", describe(reason).detail);
        }
      }),
    [change, toast],
  );

  const checkEmail = useCallback(
    () =>
      change("mail-check", async () => {
        try {
          await checkMailNow();
          setBoard((b) => (b ? { ...b, mail: { ...b.mail, running: true } } : b));
        } catch (reason) {
          toast.error("Could not check email", describe(reason).detail);
        }
      }),
    [change, toast],
  );

  return { board, loadError, busy, move, acceptEmail, dismissEmail, undoAutoClose, checkEmail };
}

export type TrackerActions = ReturnType<typeof useTrackerBoard>;
