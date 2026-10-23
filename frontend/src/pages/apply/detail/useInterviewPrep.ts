import { useEffect, useState } from "react";
import {
  getInterviewPreps,
  makeInterviewPrep,
  type InterviewPrep,
  type PrepStage,
} from "../../../api";
import { describe } from "../../../lib/errors";
import { useToast } from "../../../lib/toast";

/** Saved preps for one application, keyed by round, and Prepare for one round. */
export function useInterviewPrep(sourceJobId: string) {
  const toast = useToast();
  const [preps, setPreps] = useState<Partial<Record<PrepStage, InterviewPrep>>>({});
  const [loaded, setLoaded] = useState(false);
  const [making, setMaking] = useState<PrepStage | null>(null);

  useEffect(() => {
    let live = true;
    getInterviewPreps(sourceJobId)
      .then(({ preps: saved }) => {
        if (live) setPreps(Object.fromEntries(saved.map((prep) => [prep.stage, prep])));
      })
      .catch(() => undefined)
      .finally(() => live && setLoaded(true));
    return () => {
      live = false;
    };
  }, [sourceJobId]);

  async function make(stage: PrepStage) {
    setMaking(stage);
    try {
      const prep = await makeInterviewPrep(sourceJobId, stage);
      setPreps((current) => ({ ...current, [stage]: prep }));
    } catch (reason) {
      toast.error("Could not prepare", describe(reason).detail);
    } finally {
      setMaking(null);
    }
  }

  return { preps, loaded, making, make };
}
