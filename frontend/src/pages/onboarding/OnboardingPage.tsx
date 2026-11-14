import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { getOnboarding, putOnboarding, type OnboardingState } from "../../api";
import { Button, CommandBar, Page, Stepper } from "../../components/ui";
import { WIDE, useMediaQuery } from "../../lib/useMediaQuery";
import { describe } from "../../lib/errors";
import {
  FIRST_APPLY_STEP,
  ONBOARDING_STEPS,
  STAGE_TITLES,
  endsStageOne,
  stageOf,
  stageSteps,
  stepIndex,
  type OnboardingStep,
} from "../../lib/onboarding";
import { useToast } from "../../lib/toast";
import { useConfirm } from "../../state/confirmState";
import {
  ApplicationStep,
  ApplySetupStep,
  ContentStep,
  DoneStep,
  FieldStep,
  PersonalStep,
  ResumeStep,
  SummaryStep,
  ToolsStep,
} from "./OnboardingSteps";
import type { StepNav } from "./StepFrame";

/**
 * Setup wizard (`/welcome`), in two stages. Stage 1 is what tailoring needs: the rest of
 * the app stays closed until its last step is left or "Skip setup for now". Stage 2 is
 * what applying needs and runs with the app open, started from the Getting started guide.
 * Valid edits and progress are saved on navigation; invalid drafts stay in the providers
 * when leaving a step.
 */
export function OnboardingPage() {
  const toast = useToast();
  const navigate = useNavigate();
  const { confirm } = useConfirm();
  const [state, setState] = useState<OnboardingState | null>(null);
  const [saving, setSaving] = useState(false);
  const saveRef = useRef<(mode?: "forward" | "leave") => Promise<boolean>>(() =>
    Promise.resolve(true),
  );
  const locked = useRef(false);
  const [loadError, setLoadError] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const [returning, setReturning] = useState(false);
  const wide = useMediaQuery(WIDE);

  useEffect(() => {
    setLoadError(false);
    let live = true;
    getOnboarding()
      .then((value) => live && setState(value))
      .catch(() => live && setLoadError(true));
    return () => {
      live = false;
    };
  }, [attempt]);

  useEffect(() => {
    document.getElementById("step-title")?.focus();
    window.scrollTo({ top: 0 });
  }, [state?.step]);

  async function move(save: () => Promise<boolean>, go: () => Promise<unknown>) {
    if (locked.current) return;
    locked.current = true;
    setSaving(true);
    try {
      if (await save()) await go();
      else
        requestAnimationFrame(() =>
          document.querySelector<HTMLElement>('[aria-invalid="true"]')?.focus(),
        );
    } catch (err) {
      toast.error("Could not save setup", describe(err).detail);
    } finally {
      locked.current = false;
      setSaving(false);
    }
  }

  async function update(patch: Parameters<typeof putOnboarding>[0]) {
    try {
      const next = await putOnboarding(patch);
      setState(next);
      window.scrollTo({ top: 0 });
      return next;
    } catch (err) {
      toast.error("Could not save setup progress", describe(err).detail);
      return null;
    }
  }

  if (!state) {
    if (loadError)
      return (
        <div role="alert">
          Could not load setup progress.{" "}
          <Button onClick={() => setAttempt((n) => n + 1)}>Retry</Button>
        </div>
      );
    return (
      <p role="status" className="py-12 text-center text-sm text-ink-muted">
        Loading…
      </p>
    );
  }

  const step = state.step;
  const current = stepIndex(step);
  const stage = stageOf(step);
  const inStage = stageSteps(stage);
  const skippedSteps = state.skipped_steps ?? [];
  // Once the app is open, moving between steps never closes it again.
  const goTo = (target: OnboardingStep) =>
    update(
      state.completed ? { step: target } : { step: target, completed: false, skipped: false },
    );
  const following = ONBOARDING_STEPS[Math.min(current + 1, ONBOARDING_STEPS.length - 1)].id;
  const without = skippedSteps.filter((s) => s !== step);
  // Leaving the last stage-1 step forward (Next or Skip) opens the app on the Tailor page.
  const finishes = endsStageOne(step) && !state.completed;
  const openApp = async (skipped_steps: OnboardingStep[]) => {
    if (await update({ completed: true, step: FIRST_APPLY_STEP, skipped_steps })) navigate("/");
  };
  const forward = (skipped_steps: OnboardingStep[]) =>
    finishes
      ? openApp(skipped_steps)
      : update({ step: returning ? "review" : following, skipped_steps });
  const nav: StepNav = {
    onBack:
      current > 0 ? () => goTo(returning ? "review" : ONBOARDING_STEPS[current - 1].id) : undefined,
    onNext: () =>
      step === "review"
        ? update({ completed: true, apply_done: true, step: "done", skipped_steps: without })
        : forward(without),
    onSkip: () => forward([...without, step]),
    saving,
    saveRef,
    move,
    returning: returning && step !== "review",
    finishes,
    position:
      step === "done"
        ? undefined
        : `${STAGE_TITLES[stage]} · Step ${inStage.findIndex((s) => s.id === step) + 1} of ${inStage.length}`,
  };

  async function jump(index: number) {
    await move(
      () => saveRef.current("leave"),
      async () => {
        setReturning(step === "review" || state?.apply_done === true);
        await goTo(ONBOARDING_STEPS[index].id);
      },
    );
  }

  async function skipAll() {
    const ok = await confirm({
      title: "Leave setup?",
      message:
        "Anything you haven't set up won't work yet: tailoring needs a model and your resume, and autofill needs your application details. The setup checklist in the sidebar brings you back here.",
      confirmLabel: "Skip setup",
    });
    if (!ok) return;
    await move(
      () => saveRef.current("leave"),
      async () => {
        if (await update({ skipped: true })) navigate("/");
      },
    );
  }

  return (
    <Page width="wide" className="-mb-12 -mt-5">
      <CommandBar title={state.completed ? "Set up applying" : "Set up ResumeTailor"} />
      <div className="grid min-w-0 lg:grid-cols-[16rem_minmax(0,1fr)]">
        <nav
          aria-label="Setup"
          className="-mx-4 flex flex-col gap-4 border-b border-line bg-panel px-4 py-5 sm:-mx-6 sm:px-6 lg:mx-0 lg:-ml-6 lg:min-h-[calc(100vh-var(--rt-bar-top)-var(--rt-bar-bottom))] lg:border-b-0 lg:border-r"
        >
          {([1, 2] as const).map((n) => {
            const steps = stageSteps(n);
            const offset = stepIndex(steps[0].id);
            return (
              <div key={n}>
                <p className="mb-2 px-1 text-xs font-medium text-ink-muted">{STAGE_TITLES[n]}</p>
                <Stepper
                  steps={steps.map((s) => ({ ...s, skipped: skippedSteps.includes(s.id) }))}
                  current={current - offset}
                  label={`${STAGE_TITLES[n]} steps`}
                  orientation={wide ? "vertical" : "horizontal"}
                  disabled={saving}
                  allowJump={n === 1 ? state.completed : state.apply_done || step === "review"}
                  onSelect={(index) => void jump(offset + index)}
                />
              </div>
            );
          })}
          {!state.completed && (
            <button
              type="button"
              className="rt-link mt-auto self-start text-xs"
              onClick={() => void skipAll()}
              disabled={saving}
            >
              Skip setup for now
            </button>
          )}
        </nav>
        <div className="min-w-0 pt-6 lg:pl-10 lg:pt-8">
          {step === "field" && (
            <FieldStep nav={nav} saveField={async (field) => !!(await update({ field }))} />
          )}
          {step === "tools" && <ToolsStep nav={nav} />}
          {step === "resume" && (
            <ResumeStep
              nav={nav}
              fromScratch={state.resume_from_scratch}
              onScratch={() =>
                void move(
                  () => saveRef.current("leave"),
                  () =>
                    update({
                      resume_from_scratch: true,
                      step: returning ? "review" : following,
                      skipped_steps: without,
                    }),
                )
              }
            />
          )}
          {step === "personal" && <PersonalStep nav={nav} />}
          {step === "content" && <ContentStep nav={nav} />}
          {step === "application" && (
            <ApplicationStep nav={nav} onEditResume={() => void goTo("content")} />
          )}
          {step === "apply_tools" && <ApplySetupStep nav={nav} />}
          {step === "review" && (
            <SummaryStep
              nav={nav}
              skipped={skippedSteps}
              fromScratch={state.resume_from_scratch}
              onEdit={(target) =>
                void move(
                  () => saveRef.current("leave"),
                  async () => {
                    setReturning(true);
                    await goTo(target);
                  },
                )
              }
            />
          )}
          {step === "done" && (
            <DoneStep
              onFinish={(ready) => navigate(ready ? "/applications" : "/")}
              onEdit={() =>
                void move(
                  () => Promise.resolve(true),
                  () => goTo("review"),
                )
              }
              saving={saving}
            />
          )}
        </div>
      </div>
    </Page>
  );
}
