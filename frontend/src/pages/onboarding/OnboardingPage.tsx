import { StepFrame } from "./StepFrame";
import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  getOnboarding,
  putOnboarding,
  type OnboardingField,
  type OnboardingState,
} from "../../api";
import { Button, Page, PageHeader, Stepper } from "../../components/ui";
import { describe } from "../../lib/errors";
import { ONBOARDING_STEPS, stepIndex, type OnboardingStep } from "../../lib/onboarding";
import { useToast } from "../../lib/toast";
import { ModelsSection } from "../settings/ModelsSection";
import { BasicsStep, DoneStep, FieldStep, ResumeStep, ReviewStep } from "./OnboardingSteps";

/**
 * First-run wizard (`/welcome`). Every step saves where the student got to, so closing
 * the app mid-way resumes here. Each step can be skipped; "Skip setup" leaves the
 * wizard for good (the header's setup checklist links back to it).
 */
export function OnboardingPage() {
  const toast = useToast();
  const navigate = useNavigate();
  const [state, setState] = useState<OnboardingState | null>(null);
  const [saving, setSaving] = useState(false);

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

  const current = stepIndex(state.step);
  const goTo = (step: OnboardingStep) => update({ step });
  const next = () => goTo(ONBOARDING_STEPS[Math.min(current + 1, ONBOARDING_STEPS.length - 1)].id);
  const back = current > 0 ? () => goTo(ONBOARDING_STEPS[current - 1].id) : undefined;

  async function skipAll() {
    if (await update({ skipped: true })) navigate("/");
  }

  return (
    <Page className="max-w-3xl!">
      <PageHeader
        eyebrow={state.step === "done" ? "SETUP · COMPLETE" : `SETUP · STEP ${current + 1} OF 5`}
        title="Welcome to ResumeTailor"
        description="Five short steps. You can change any of this later in Settings."
        actions={
          !state.completed && (
            <Button variant="ghost" size="sm" onClick={skipAll} disabled={saving}>
              Skip setup for now
            </Button>
          )
        }
      />
      <Stepper
        steps={ONBOARDING_STEPS.filter((step) => step.id !== "done")}
        current={current}
        label="Setup steps"
        onSelect={(index) => void goTo(ONBOARDING_STEPS[index].id)}
      />
      {state.step === "field" && (
        <FieldStep
          field={state.field}
          saving={saving}
          onChoose={(field: OnboardingField) => update({ field, step: "model" })}
        />
      )}
      {state.step === "model" && (
        <StepFrame
          title="Choose the AI that writes for you"
          intro="Ollama runs free on this computer. A paid API key gives better writing for a few cents per resume. You can change this any time in Settings."
          onBack={back}
          onNext={next}
          saving={saving}
        >
          <ModelsSection />
        </StepFrame>
      )}
      {state.step === "resume" && (
        <StepFrame
          title="Add your resume"
          intro="Upload your resume as a Word (.docx) file. ResumeTailor keeps its exact look and only changes the words."
          onBack={back}
          onNext={next}
          nextLabel="Continue"
          saving={saving}
        >
          <ResumeStep onScratch={next} />
        </StepFrame>
      )}
      {state.step === "review" && (
        <StepFrame
          title="Check what we found"
          intro="Everything tailored later comes from this content, so fix anything missing now."
          onBack={back}
          onNext={next}
          saving={saving}
        >
          <ReviewStep />
        </StepFrame>
      )}
      {state.step === "basics" && (
        <StepFrame
          title="Application basics (optional)"
          intro="Only used to fill in job application forms. Skip it if you only want tailored resumes."
          saving={saving}
        >
          <BasicsStep
            onDone={() => update({ completed: true })}
            onSkip={next}
            onBack={() => void goTo("review")}
          />
        </StepFrame>
      )}
      {state.step === "done" && (
        <DoneStep
          onFinish={async () => {
            if (state.completed || (await update({ completed: true }))) navigate("/");
          }}
          saving={saving}
        />
      )}
    </Page>
  );
}
