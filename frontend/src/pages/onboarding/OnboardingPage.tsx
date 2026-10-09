import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { getOnboarding, putOnboarding, type OnboardingState } from "../../api";
import { Button, Page, PageHeader, Stepper } from "../../components/ui";
import { describe } from "../../lib/errors";
import { ONBOARDING_STEPS, stepIndex, type OnboardingStep } from "../../lib/onboarding";
import { useToast } from "../../lib/toast";
import { useConfirm } from "../../state/confirmState";
import {
  ApplicationStep,
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
 * First-run wizard (`/welcome`). Every move (Back, Skip, Next, a stepper jump) saves the
 * page first, and the step reached is stored, so closing the app mid-way resumes here.
 * The rest of the app stays closed until setup is finished or "Skip setup for now".
 */
export function OnboardingPage() {
  const toast = useToast();
  const navigate = useNavigate();
  const { confirm } = useConfirm();
  const [state, setState] = useState<OnboardingState | null>(null);
  const [saving, setSaving] = useState(false);
  const saveRef = useRef<() => Promise<boolean>>(() => Promise.resolve(true));

  useEffect(() => {
    getOnboarding()
      .then(setState)
      .catch((err) => toast.error("Could not load setup progress", describe(err).detail));
  }, [toast]);

  async function update(patch: Parameters<typeof putOnboarding>[0]) {
    setSaving(true);
    try {
      const next = await putOnboarding(patch);
      setState(next);
      window.scrollTo({ top: 0 });
      return next;
    } catch (err) {
      toast.error("Could not save setup progress", describe(err).detail);
      return null;
    } finally {
      setSaving(false);
    }
  }

  if (!state) {
    return (
      <p role="status" className="py-12 text-center text-sm text-ink-muted">
        Loading…
      </p>
    );
  }

  const step = state.step;
  const current = stepIndex(step);
  const skippedSteps = state.skipped_steps ?? [];
  const goTo = (target: OnboardingStep) => update({ step: target });
  const following = ONBOARDING_STEPS[Math.min(current + 1, ONBOARDING_STEPS.length - 1)].id;
  const without = skippedSteps.filter((s) => s !== step);
  const nav: StepNav = {
    onBack: current > 0 ? () => void goTo(ONBOARDING_STEPS[current - 1].id) : undefined,
    onNext: () =>
      void update(
        step === "review"
          ? { completed: true, skipped_steps: without }
          : { step: following, skipped_steps: without },
      ),
    onSkip: () => void update({ step: following, skipped_steps: [...without, step] }),
    saving,
    saveRef,
  };

  async function jump(index: number) {
    if (await saveRef.current()) void goTo(ONBOARDING_STEPS[index].id);
  }

  async function skipAll() {
    const ok = await confirm({
      title: "Leave setup?",
      message:
        "Anything you haven't set up won't work yet: tailoring needs a model and your resume, and autofill needs your application details. The setup checklist in the header brings you back here.",
      confirmLabel: "Skip setup",
    });
    if (!ok || !(await saveRef.current())) return;
    if (await update({ skipped: true })) navigate("/");
  }

  return (
    <Page>
      <PageHeader
        title="Welcome to ResumeTailor"
        description="Set up once and you're ready to tailor and apply. Everything can be changed later."
        actions={
          !state.completed && (
            <Button variant="ghost" size="sm" onClick={() => void skipAll()} disabled={saving}>
              Skip setup for now
            </Button>
          )
        }
      />
      <Stepper
        steps={ONBOARDING_STEPS.filter((s) => s.id !== "done")}
        current={current}
        label="Setup steps"
        stretch
        onSelect={state.completed ? undefined : (index) => void jump(index)}
      />
      {step === "field" && (
        <FieldStep nav={nav} saveField={async (field) => !!(await update({ field }))} />
      )}
      {step === "tools" && <ToolsStep nav={nav} />}
      {step === "resume" && (
        <ResumeStep
          nav={nav}
          fromScratch={state.resume_from_scratch}
          onScratch={() =>
            void update({ resume_from_scratch: true, step: following, skipped_steps: without })
          }
        />
      )}
      {step === "personal" && <PersonalStep nav={nav} />}
      {step === "content" && <ContentStep nav={nav} />}
      {step === "application" && (
        <ApplicationStep nav={nav} onEditResume={() => void goTo("content")} />
      )}
      {step === "review" && (
        <SummaryStep
          nav={nav}
          skipped={skippedSteps}
          fromScratch={state.resume_from_scratch}
          onEdit={(target) => void goTo(target)}
        />
      )}
      {step === "done" && <DoneStep onFinish={() => navigate("/")} saving={saving} />}
    </Page>
  );
}
