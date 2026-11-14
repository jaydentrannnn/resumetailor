import {
  type ReactNode,
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from "react";
import { useLocation } from "react-router-dom";
import { fetchSetupStatus, getApplyProgress, getOnboarding, putOnboarding } from "../api";
import { onAppEvent } from "../lib/appEvents";
import { guideActive, guideSteps, type GuideStep } from "../lib/guide";
import { useRunState } from "./runState";

type GuideValue = {
  /** The six steps, or null while unknown, hidden, or first-run setup is still running. */
  steps: GuideStep[] | null;
  /** The guide should be on screen: not hidden, and a step is still open. */
  active: boolean;
  dismissed: boolean;
  /** Stage 2 of setup is finished; null until setup progress has loaded. */
  applyDone: boolean | null;
  hide: () => Promise<void>;
  show: () => Promise<void>;
};

const OFF: GuideValue = {
  steps: null,
  active: false,
  dismissed: false,
  applyDone: null,
  hide: () => Promise.resolve(),
  show: () => Promise.resolve(),
};

const GuideContext = createContext<GuideValue>(OFF);

/**
 * The Getting started guide's state, read by the Tailor page, the rail pill, Apply's empty
 * state and Ctrl+K. Everything comes from endpoints that already exist; it is re-read on
 * navigation, when setup changes and when a run finishes. A hidden guide costs one small
 * request per navigation (setup progress) and nothing more. Advisory: a failed read
 * leaves the last known state.
 */
export function GuideProvider({ children }: { children: ReactNode }) {
  const { pathname } = useLocation();
  const runs = useRunState().history.length;
  const [dismissed, setDismissed] = useState(false);
  const [applyDone, setApplyDone] = useState<boolean | null>(null);
  const [steps, setSteps] = useState<GuideStep[] | null>(null);
  const [revision, setRevision] = useState(0);

  useEffect(() => onAppEvent("rt:setup-changed", () => setRevision((n) => n + 1)), []);

  useEffect(() => {
    let live = true;
    void (async () => {
      try {
        const onboarding = await getOnboarding();
        if (!live) return;
        setDismissed(onboarding.guide_dismissed);
        setApplyDone(onboarding.apply_done);
        // No guide over the first-run wizard, and nothing more to read once it is hidden.
        if (onboarding.guide_dismissed || (!onboarding.completed && !onboarding.skipped)) {
          setSteps(null);
          return;
        }
        const [setup, progress] = await Promise.all([fetchSetupStatus(), getApplyProgress()]);
        if (live) setSteps(guideSteps({ setup, runs, applyDone: onboarding.apply_done, progress }));
      } catch {
        /* advisory: keep what was known */
      }
    })();
    return () => {
      live = false;
    };
  }, [pathname, runs, revision]);

  const set = useCallback(async (hidden: boolean) => {
    setDismissed(hidden);
    try {
      await putOnboarding({ guide_dismissed: hidden });
    } finally {
      setRevision((n) => n + 1);
    }
  }, []);

  const value = useMemo<GuideValue>(
    () => ({
      steps,
      active: guideActive(dismissed, steps),
      dismissed,
      applyDone,
      hide: () => set(true),
      show: () => set(false),
    }),
    [steps, dismissed, applyDone, set],
  );
  return <GuideContext.Provider value={value}>{children}</GuideContext.Provider>;
}

/** The guide's state; outside `GuideProvider` (tests) it reads as off. */
export function useGuide(): GuideValue {
  return useContext(GuideContext);
}
