import { useEffect, useState } from "react";
import { getSkillGaps, type SkillGaps } from "../../../api";

/**
 * The skill-gap numbers, read when ``enabled`` and again on a profile change or page
 * refresh (``revision``). A failed read shows nothing, like the rest of the banner.
 */
export function useSkillGaps(
  workspaceId: string,
  revision: number,
  enabled: boolean,
): SkillGaps | null {
  const [gaps, setGaps] = useState<SkillGaps | null>(null);
  useEffect(() => {
    if (!enabled) return;
    let live = true;
    getSkillGaps()
      .then((next) => live && setGaps(next))
      .catch(() => undefined);
    return () => {
      live = false;
    };
  }, [workspaceId, revision, enabled]);
  return enabled ? gaps : null;
}
