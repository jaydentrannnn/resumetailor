import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { fetchUpdateStatus, type UpdateStatus } from "../api";
import { updateChipLabel, updateChipVisible } from "../lib/updateStatus";

const POLL_MS = 30 * 60_000;

/**
 * Header chip when a desktop-app update is available or installing; links to
 * Settings → About. Checks on load, every 30 minutes while the tab is visible, and when
 * the tab becomes visible again. Renders nothing in dev and Docker.
 */
export function UpdateChip() {
  const [status, setStatus] = useState<UpdateStatus | null>(null);

  const load = useCallback(() => {
    fetchUpdateStatus()
      .then(setStatus)
      .catch(() => setStatus(null)); // advisory: hide on failure
  }, []);

  useEffect(() => {
    load();
    const timer = window.setInterval(() => {
      if (document.visibilityState === "visible") load();
    }, POLL_MS);
    const onVisible = () => {
      if (document.visibilityState === "visible") load();
    };
    document.addEventListener("visibilitychange", onVisible);
    return () => {
      window.clearInterval(timer);
      document.removeEventListener("visibilitychange", onVisible);
    };
  }, [load]);

  if (!status || !updateChipVisible(status)) return null;
  return (
    <Link
      to="/settings?tab=about"
      className="rounded-full border border-accent/40 bg-accent-soft px-3 py-1 text-xs font-semibold text-accent"
    >
      <span aria-hidden="true">↑ </span>
      {updateChipLabel(status)}
    </Link>
  );
}
