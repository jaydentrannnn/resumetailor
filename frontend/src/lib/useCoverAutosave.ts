import { useCallback, useEffect, useRef, useState } from "react";
import type { CoverLetterSettings } from "../api";
import { describe } from "./errors";

/**
 * Cover-letter settings that save as they change: `change` updates the shown settings at
 * once and saves after `delayMs` of quiet (typing in a field coalesces into one save).
 * A failed save shows `error` and puts the controls back to what was last saved. A
 * pending save is sent when the view unmounts (switching to the Resume view).
 */
export function useCoverAutosave(
  saved: CoverLetterSettings | null,
  save: (next: CoverLetterSettings) => Promise<void>,
  delayMs = 500,
) {
  const [draft, setDraft] = useState<CoverLetterSettings | null>(saved);
  const [error, setError] = useState<string | null>(null);
  const pending = useRef<CoverLetterSettings | null>(null);
  const timer = useRef<number | undefined>(undefined);
  const lastSaved = useRef(saved);
  const saveRef = useRef(save);
  saveRef.current = save;

  useEffect(() => {
    lastSaved.current = saved;
    if (!pending.current) setDraft(saved);
  }, [saved]);

  const flush = useCallback(() => {
    window.clearTimeout(timer.current);
    const next = pending.current;
    pending.current = null;
    if (!next || JSON.stringify(next) === JSON.stringify(lastSaved.current)) return;
    saveRef
      .current(next)
      .then(() => setError(null))
      .catch((reason) => {
        setError(describe(reason).detail);
        if (!pending.current) setDraft(lastSaved.current);
      });
  }, []);

  const change = useCallback(
    (next: CoverLetterSettings) => {
      setDraft(next);
      pending.current = next;
      window.clearTimeout(timer.current);
      timer.current = window.setTimeout(flush, delayMs);
    },
    [flush, delayMs],
  );

  useEffect(() => flush, [flush]);
  return { draft, change, error };
}
