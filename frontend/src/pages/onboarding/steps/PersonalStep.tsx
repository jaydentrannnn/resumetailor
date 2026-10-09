import { useEffect, useState } from "react";
import { SKIP_WARNINGS, personalComplete } from "../../../lib/onboarding";
import { useEditorState } from "../../../state/editorState";
import { PersonalTab } from "../../profile/PersonalTab";
import { useProfileFields } from "../../profile/useProfileFields";
import { StepFrame, type StepNav } from "../StepFrame";
import { saveProfileStep } from "./saveProfileStep";

/** Step 4: the Profile page's Personal information tab, prefilled from the resume header. */
export function PersonalStep({ nav }: { nav: StepNav }) {
  const fields = useProfileFields();
  const { applicant, draft, ctx, allErrors } = fields;
  const editor = useEditorState();
  const [prefilled, setPrefilled] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Seed empty names from the resume's header once, so most students only confirm. Email
  // and phone stay blank: blank means "use the resume contact" on application forms.
  useEffect(() => {
    if (prefilled || !draft || !editor.resume) return;
    setPrefilled(true);
    const contact = editor.resume.contact;
    const [first, ...rest] =
      contact.name && contact.name !== "Your Name" ? contact.name.trim().split(/\s+/) : [];
    const patch = {
      first_name: draft.first_name || first || "",
      last_name: draft.last_name || rest.join(" "),
    };
    if (Object.entries(patch).some(([k, v]) => v !== draft[k as keyof typeof draft]))
      applicant.setDraft({ ...draft, ...patch });
  }, [draft, editor.resume, prefilled, applicant]);

  return (
    <StepFrame
      title="Personal information"
      intro="Printed on your resume and used for the contact fields on application forms."
      nav={nav}
      complete={personalComplete(draft, allErrors, editor.resume?.contact, applicant.fallbacks)}
      onSave={() => saveProfileStep(fields, editor, setError)}
      skipWarning={SKIP_WARNINGS.personal}
      error={error}
    >
      {ctx ? (
        <PersonalTab ctx={ctx} resume={editor.resume} setResume={editor.setResume} />
      ) : (
        <p className="text-sm text-ink-muted">{applicant.error ?? "Loading your profile…"}</p>
      )}
    </StepFrame>
  );
}
