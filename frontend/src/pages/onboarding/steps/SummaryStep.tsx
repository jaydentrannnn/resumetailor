import type { ReactNode } from "react";
import type { OnboardingStepId } from "../../../api";
import { Button, DataList, StatusChip, TileSection } from "../../../components/ui";
import { browserLabel } from "../../../lib/browserState";
import { tailorModelLabel } from "../../../lib/modelLabel";
import { applicationSummary, reviewResume } from "../../../lib/onboarding";
import { CHOICE_FIELDS, PROFILE_GROUPS, fieldLabel } from "../../../lib/profileForm";
import { modelsFor, selectionLabel } from "../../../lib/aiModels";
import { FIELD_LABELS } from "../../../lib/sources";
import { useApplicantProfile } from "../../../state/applicantProfileState";
import { useEditorState } from "../../../state/editorState";
import { useRunState } from "../../../state/runState";
import { useTemplateState } from "../../../state/templateState";
import { StepFrame, type StepNav } from "../StepFrame";

/** The first few names, then a count, so a long list stays one line. */
function listSummary(names: string[]): string {
  if (!names.length) return "—";
  return names.length <= 3
    ? names.join(", ")
    : `${names.slice(0, 3).join(", ")} and ${names.length - 3} more`;
}

/** Step 7: what the student entered, step by step and in that order, before finishing. */
export function SummaryStep({
  nav,
  skipped,
  fromScratch,
  onEdit,
}: {
  nav: StepNav;
  skipped: OnboardingStepId[];
  fromScratch: boolean;
  onEdit: (step: OnboardingStepId) => void;
}) {
  const { config, settings } = useRunState();
  const { draft, dirty: profileDirty } = useApplicantProfile();
  const { resume, dirty: resumeDirty } = useEditorState();
  const { info } = useTemplateState();
  const apply = settings.apply;
  const target = config?.target_fields?.find((f) => f.id === config?.target_field);
  const review = reviewResume(resume);
  const contact = resume?.contact;
  const name = draft?.first_name ? [draft.first_name, draft.last_name].join(" ").trim() : "";
  const answers = applicationSummary(
    draft as Record<string, unknown> | null,
    PROFILE_GROUPS,
    CHOICE_FIELDS,
    fieldLabel,
  );
  const none = "—";

  const section = (step: OnboardingStepId, title: string, body: ReactNode) => (
    <TileSection
      title={title}
      actions={
        <>
          {skipped.includes(step) && <StatusChip tone="attention">Skipped</StatusChip>}
          <Button variant="plain" size="sm" onClick={() => onEdit(step)}>
            Edit
          </Button>
        </>
      }
    >
      {body}
    </TileSection>
  );

  return (
    <StepFrame
      title="Review your setup"
      intro="Everything you entered, in order. Edit anything before you finish; all of it can be changed later too."
      nav={nav}
      complete
      nextLabel="Save and finish"
    >
      <div className="space-y-4">
        <p className="text-sm text-attn">
          Finishing saves your setup progress. Tailoring still needs a working model, a template and
          resume content. Skipped steps can be edited later.
        </p>
        {(profileDirty || resumeDirty) && (
          <p role="alert" className="text-sm text-attn">
            Some edits are still unsaved. Return to their step to fix and save them; they remain in
            this window.
          </p>
        )}
        {section(
          "field",
          "Your field",
          <DataList
            items={[
              { label: "Target field", value: target?.label ?? none },
              {
                label: "Jobs to look for",
                value: (apply.fields ?? []).map((f) => FIELD_LABELS[f]).join(", ") || none,
              },
              {
                label: "Job lists",
                value: listSummary(
                  apply.sources.filter((s) => s.enabled).map((s) => s.name || s.id),
                ),
              },
            ]}
          />,
        )}
        {section(
          "tools",
          "AI & browser",
          <DataList
            items={[
              { label: "Light task model", value: tailorModelLabel(settings, config) },
              {
                label: "Heavy task model",
                value: selectionLabel(modelsFor(settings).heavy, config),
              },
              {
                label: "Browser",
                value: apply.browser ? browserLabel(apply.browser) : "Automatic",
              },
            ]}
          />,
        )}
        {section(
          "resume",
          "Your resume",
          <DataList
            items={[
              {
                label: "Template",
                value: info?.tagged.exists
                  ? (info.active_label ?? "Installed")
                  : fromScratch
                    ? "Starting from scratch"
                    : none,
              },
            ]}
          />,
        )}
        {section(
          "personal",
          "Personal information",
          <DataList
            items={[
              { label: "Name", value: name || contact?.name || none },
              { label: "Email", value: draft?.email || contact?.email || none },
              { label: "Phone", value: draft?.phone || contact?.phone || none },
              ...(contact?.linkedin ? [{ label: "LinkedIn", value: contact.linkedin }] : []),
              ...(contact?.github ? [{ label: "GitHub", value: contact.github }] : []),
            ]}
          />,
        )}
        {section(
          "content",
          "Resume content",
          <DataList
            items={[
              { label: "Entries", value: review.entries },
              { label: "Bullet points", value: review.bullets },
            ]}
          />,
        )}
        {section(
          "application",
          "Application details",
          answers.length ? (
            <DataList items={answers} />
          ) : (
            <p className="text-sm text-ink-muted">Nothing entered yet.</p>
          ),
        )}
      </div>
    </StepFrame>
  );
}
