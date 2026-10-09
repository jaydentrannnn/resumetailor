import { useState } from "react";
import { ALL_PROFILE_GROUP_IDS, GAP_FIELD_ALIASES, withGroupOpen } from "../../../lib/profileForm";
import { SKIP_WARNINGS, openGaps } from "../../../lib/onboarding";
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
  const { applicant, draft, ctx } = fields;
  const editor = useEditorState();
  const [open, setOpen] = useState<Set<string>>(() => new Set(ALL_PROFILE_GROUP_IDS));
  const [error, setError] = useState<string | null>(null);
  const education = editor.resume?.sections.find((s) => s.kind === "education");
  const required = applicant.gaps
    .filter((gap) => gap.path === "/profile/application")
    .map((gap) => GAP_FIELD_ALIASES[gap.key] ?? gap.key);
  const remaining = openGaps(required, draft as Record<string, unknown> | null);

  return (
    <StepFrame
      title="Application details"
      intro="The facts application forms ask for. Autofill uses them so it doesn't stop to ask you."
      nav={nav}
      complete={!!draft && remaining.length === 0}
      onSave={() => saveProfileStep(fields, editor, setError)}
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
