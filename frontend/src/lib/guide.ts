import type { ApplyProgress, SetupStatus } from "../api";

/**
 * The Getting started guide: the six things a new student does, in order, each ticked
 * from what the app already knows (never from a click on the guide itself).
 */
export type GuideStepId = "setup" | "tailor" | "apply_setup" | "find" | "fill" | "send";

export interface GuideStep {
  id: GuideStepId;
  title: string;
  /** One sentence: what to do. */
  detail: string;
  done: boolean;
  /** Where the step is done, and what the button that goes there says. */
  to: string;
  action: string;
}

export interface GuideInputs {
  setup: SetupStatus;
  /** Tailored resumes in this profile's history. */
  runs: number;
  /** Stage 2 of setup (what applying needs) is finished. */
  applyDone: boolean;
  progress: Pick<ApplyProgress, "found" | "autofilled" | "sent_total">;
}

export function guideSteps({ setup, runs, applyDone, progress }: GuideInputs): GuideStep[] {
  // "Finish setup" opens the first thing still missing, not the wizard's current step.
  const missing = setup.items.find((item) => !item.ok && !item.optional);
  return [
    {
      id: "setup",
      title: "Finish setup",
      detail: missing
        ? `${missing.label}: ${missing.detail}`
        : "Your resume, its template and an AI model are in place.",
      done: setup.ready,
      to: missing?.fix.to ?? "/welcome",
      action: missing?.fix.label ?? "Open setup",
    },
    {
      id: "tailor",
      title: "Tailor your first resume",
      detail: "Paste a job posting on the Tailor page and press Tailor resume.",
      done: runs > 0,
      to: "/",
      action: "Open Tailor",
    },
    {
      id: "apply_setup",
      title: "Set up applying",
      detail: "Add the details application forms ask for, your job lists and a browser.",
      done: applyDone,
      to: "/welcome",
      action: "Set up applying",
    },
    {
      id: "find",
      title: "Find jobs",
      detail: "On Apply, press Find jobs to search your job lists for new postings.",
      done: progress.found > 0,
      to: "/applications",
      action: "Open Apply",
    },
    {
      id: "fill",
      title: "Fill your first application",
      detail:
        "Pick a posting on Apply and press Fill: the form is filled in your browser, and the app stops wherever it needs you.",
      done: progress.autofilled > 0,
      to: "/applications",
      action: "Open Apply",
    },
    {
      id: "send",
      title: "Send it and track replies",
      detail: "A sent application moves to Tracker, where replies and interviews are kept.",
      done: progress.sent_total > 0,
      to: "/tracker",
      action: "Open Tracker",
    },
  ];
}

/** How far along the guide is, and the first step still open (the one to do next). */
export function guideProgress(steps: GuideStep[]): {
  done: number;
  total: number;
  next: GuideStep | null;
} {
  return {
    done: steps.filter((step) => step.done).length,
    total: steps.length,
    next: steps.find((step) => !step.done) ?? null,
  };
}

/** The guide shows until it is hidden or every step is done. */
export function guideActive(dismissed: boolean, steps: GuideStep[] | null): boolean {
  return !dismissed && !!steps && steps.some((step) => !step.done);
}

/** The rail pill while the guide is showing; short enough for the 184px rail. */
export function guidePillLabel(steps: GuideStep[]): string {
  const { done, total } = guideProgress(steps);
  return `Get started · ${done}/${total}`;
}
