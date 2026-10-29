import { useState } from "react";
import { withGroupOpen } from "../../../lib/profileForm";
import { SKIP_WARNINGS } from "../../../lib/onboarding";
import { useEditorState } from "../../../state/editorState";
import { ApplicationTab } from "../../profile/ApplicationTab";
import { useProfileFields } from "../../profile/useProfileFields";
import { StepFrame, type StepNav } from "../StepFrame";
import { saveProfileStep } from "./saveProfileStep";

/**
 * Step 6: the Profile page's Application details tab. Complete once every question the
 * app knows forms ask (the profile gaps) has an answer.
 */
export function ApplicationStep({ nav, onEditResume }: { nav: StepNav; onEditResume: () => void }) {
  const fields = useProfileFields();
  const { applicant, draft, ctx, allErrors } = fields;
  const editor = useEditorState();
  const [open, setOpen] = useState<Set<string>>(() => new Set<string>());
  const [error, setError] = useState<string | null>(null);
  const education = editor.resume?.sections.find((s) => s.kind === "education");

  return (
    <StepFrame
      title="Application details"
      intro="Optional: add answers you want autofill to use. Leave any question blank to answer it yourself on each form. You can continue without completing these groups."
      nav={nav}
      complete={!!draft && Object.keys(allErrors).length === 0}
      onSave={(mode) => saveProfileStep(fields, editor, setError, mode)}
      skipWarning={SKIP_WARNINGS.application}
      error={error}
    >
      {ctx ? (
        <ApplicationTab
          ctx={ctx}
          open={open}
          onToggle={(id, isOpen) => setOpen((current) => withGroupOpen(current, id, isOpen))}
          onOpenGroup={(id) => {
            setOpen((current) => withGroupOpen(current, id, true));
            requestAnimationFrame(() =>
              document.getElementById(`profile-group-${id}`)?.scrollIntoView({ block: "start" }),
            );
          }}
          education={education?.kind === "education" ? education.entries : []}
          onEditResume={() =>
            void saveProfileStep(fields, editor, setError).then((ok) => ok && onEditResume())
          }
        />
      ) : (
        <p className="text-sm text-ink-muted">{applicant.error ?? "Loading your profile…"}</p>
      )}
    </StepFrame>
  );
}
