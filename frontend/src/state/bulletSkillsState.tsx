import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import { type BulletSkills, fetchBulletSkills } from "../api";

const POLL_MS = 2000;

const BulletSkillsContext = createContext<BulletSkills | null>(null);

/**
 * The skills each saved bullet shows beyond its Extra skills. Fetched whenever the
 * editor matches disk (`dirty` false: after a load or a save), then polled while the
 * background refresh that every save starts is still running.
 */
export function BulletSkillsProvider({ dirty, children }: { dirty: boolean; children: ReactNode }) {
  const [skills, setSkills] = useState<BulletSkills | null>(null);

  useEffect(() => {
    if (dirty) return;
    let stopped = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const tick = async () => {
      try {
        const next = await fetchBulletSkills();
        if (stopped) return;
        setSkills(next);
        if (next.running) timer = setTimeout(() => void tick(), POLL_MS);
      } catch {
        // Advisory only: the editor works without it.
      }
    };
    void tick();
    return () => {
      stopped = true;
      clearTimeout(timer);
    };
  }, [dirty]);

  return <BulletSkillsContext.Provider value={skills}>{children}</BulletSkillsContext.Provider>;
}

/** Computed skills for the editor, or null before the first fetch. */
export function useBulletSkills(): BulletSkills | null {
  return useContext(BulletSkillsContext);
}
