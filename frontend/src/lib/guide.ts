import type { ApplyProgress, SetupStatus } from "../api";

/**
 * The Getting started guide: the six things a new student does, in order, each ticked
 * from what the app already knows (never from a click on the guide itself).
 */
export type GuideStepId = "setup" | "tailor" | "apply_setup" | "find" | "fill" | "send" | "nightly";

export interface GuideStep {
  id: GuideStepId;
  title: string;
  /** One sentence: what to do. */
  detail: string;
  done: boolean;
  /** Where the step is done, and what the button that goes there says. */
  to: string;
  action: string;
  /** Offered, never required: not counted, and never the "next" step. */
  optional?: boolean;
}

export interface GuideInputs {
  setup: SetupStatus;
  /** Successful tailoring runs in this profile's history. */
  runs: number;
  /** Stage 2 of setup (what applying needs) is finished. */
  applyDone: boolean;
  progress: Pick<ApplyProgress, "found" | "autofilled" | "sent_total">;
  /** The nightly run is on (`apply.enabled`). */
  nightly?: boolean;
}

export function guideSteps({
  setup,
  runs,
  applyDone,
  progress,
  nightly = false,
}: GuideInputs): GuideStep[] {
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
        "On Apply, press Tailor files on a posting, then Fill when it is ready: the form is filled in your browser, and the app stops wherever it needs you.",
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
    // Offered once a first form has been filled, so the student knows what Fill does.
    ...(progress.autofilled > 0 && !nightly
      ? [
          {
            id: "nightly" as const,
            title: "Find jobs for me every night",
            detail:
              "Optional: each night the app finds new postings and tailors a resume for each, ready for you to Fill. It never fills or submits, and the app must be open or in the tray.",
            done: false,
            to: "/applications?settings=1&reveal=nightly",
            action: "Turn on the nightly run",
            optional: true,
          },
        ]
      : []),
  ];
}

/** How far along the guide is, and the first step still open (the one to do next). */
export function guideProgress(steps: GuideStep[]): {
  done: number;
  total: number;
  next: GuideStep | null;
} {
  const required = steps.filter((step) => !step.optional);
  return {
    done: required.filter((step) => step.done).length,
    total: required.length,
    next: required.find((step) => !step.done) ?? null,
  };
}

/** The guide shows until it is hidden or every step is done. */
export function guideActive(dismissed: boolean, steps: GuideStep[] | null): boolean {
  return !dismissed && !!steps && steps.some((step) => !step.done && !step.optional);
}

/** The rail pill while the guide is showing; short enough for the 184px rail. */
export function guidePillLabel(steps: GuideStep[]): string {
  const { done, total } = guideProgress(steps);
  return `Get started · ${done}/${total}`;
}
