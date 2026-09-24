import { useCallback, useEffect, useState } from "react";
import { getOpenTabs } from "../api";
import type { OpenTabs } from "./applicationRows";

/**
 * Tracks which browser tabs are still open, so a closed application tab stops offering
 * Continue. Polls every `intervalMs` and re-checks when the page regains focus (the
 * usual moment after closing a tab). `reachable` is null until the first answer.
 */
export function useOpenTabs(intervalMs = 4000) {
  const [openTabs, setOpenTabs] = useState<OpenTabs>(null);
  const [reachable, setReachable] = useState<boolean | null>(null);
  const [revision, setRevision] = useState(0);
  const recheck = useCallback(() => setRevision((n) => n + 1), []);
  useEffect(() => {
    let live = true;
    getOpenTabs()
      .then((result) => {
        if (!live) return;
        setReachable(result.reachable);
        setOpenTabs(result.reachable ? new Set(result.target_ids) : null);
      })
      .catch(() => {
        /* keep the last answer */
      });
    return () => {
      live = false;
    };
  }, [revision]);
  useEffect(() => {
    const id = window.setInterval(() => {
      if (document.visibilityState === "visible") recheck();
    }, intervalMs);
    const onVisible = () => {
      if (document.visibilityState === "visible") recheck();
    };
    window.addEventListener("focus", recheck);
    document.addEventListener("visibilitychange", onVisible);
    return () => {
      window.clearInterval(id);
      window.removeEventListener("focus", recheck);
      document.removeEventListener("visibilitychange", onVisible);
    };
  }, [intervalMs, recheck]);
  return { openTabs, reachable, recheck };
}
