import { useEffect, useState } from "react";
import { getApplyProgress, type ApplyProgress } from "../../../api";

/**
 * The progress banner's numbers, read again when the profile changes or the page
 * refreshes (`revision`). A failed read leaves the last numbers, or none: the banner is
 * a nicety, never an error.
 */
export function useApplyProgress(workspaceId: string, revision: number): ApplyProgress | null {
  const [progress, setProgress] = useState<ApplyProgress | null>(null);
  useEffect(() => {
    let live = true;
    getApplyProgress()
      .then((next) => live && setProgress(next))
      .catch(() => undefined);
    return () => {
      live = false;
    };
  }, [workspaceId, revision]);
  return progress;
}
