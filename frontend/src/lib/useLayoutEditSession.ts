import { useCallback, useEffect, useRef, useState } from "react";
import {
  endEditSession,
  fetchConfig,
  fetchEditSession,
  fetchEditedLayout,
  importEditSession,
  reopenEditSession,
  startEditSession,
  type TemplateEditStatus,
} from "../api";
import { useTemplateState } from "../state/templateState";
import { startAdaptivePoll } from "./adaptivePoll";

const IDLE: TemplateEditStatus = {
  active: false,
  changed: false,
  saved_at: null,
  editor_open: false,
  started_at: null,
  path: null,
};

/** Where the template wizard sits on the Template page, for "Review changes". */
export const WIZARD_ANCHOR = "template-import";

/**
 * The Edit-layout-in-Word session: start it, poll for the save, and hand the read-back
 * to the template wizard. Installing through the wizard ends the session.
 */
export function useLayoutEditSession() {
  const { info, wizardStep, beginFromAnalysis } = useTemplateState();
  const [desktop, setDesktop] = useState(false);
  const [status, setStatus] = useState<TemplateEditStatus>(IDLE);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const reviewing = useRef(false);
  const poll = useRef<{ stop: () => void; wake: () => void } | null>(null);

  useEffect(() => {
    let live = true;
    fetchConfig()
      .then((cfg) => live && setDesktop(Boolean(cfg.desktop)))
      .catch(() => undefined);
    return () => {
      live = false;
    };
  }, []);

  useEffect(() => {
    if (!desktop) return;
    const handle = startAdaptivePoll(async () => {
      const next = await fetchEditSession();
      setStatus(next);
      return next.active && !next.changed;
    });
    poll.current = handle;
    return () => {
      handle.stop();
      poll.current = null;
    };
  }, [desktop]);

  const run = useCallback(async (action: () => Promise<TemplateEditStatus | void>) => {
    setBusy(true);
    setError(null);
    try {
      const next = await action();
      if (next) setStatus(next);
      poll.current?.wake();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }, []);

  const start = useCallback(() => run(startEditSession), [run]);
  const reopen = useCallback(() => run(reopenEditSession), [run]);
  const discard = useCallback(
    () =>
      run(async () => {
        await endEditSession();
        reviewing.current = false;
        return IDLE;
      }),
    [run],
  );
  const review = useCallback(
    () =>
      run(async () => {
        const analysis = await importEditSession();
        const file = await fetchEditedLayout(analysis.source_sha256);
        const base = info?.active_label || "Template";
        beginFromAnalysis(file, analysis, `${base} (edited)`);
        reviewing.current = true;
        document.getElementById(WIZARD_ANCHOR)?.scrollIntoView({ behavior: "smooth" });
      }),
    [run, info?.active_label, beginFromAnalysis],
  );

  // The wizard installed the edited layout: the session has done its job.
  useEffect(() => {
    if (wizardStep !== "done" || !reviewing.current) return;
    reviewing.current = false;
    void discard();
  }, [wizardStep, discard]);

  return { desktop, status, busy, error, start, reopen, review, discard };
}
