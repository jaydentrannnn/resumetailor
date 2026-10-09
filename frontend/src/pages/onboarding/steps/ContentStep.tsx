import { ProfileGapBanner } from "../../../components/ProfileGapBanner";
import { DataList } from "../../../components/ui";
import { SKIP_WARNINGS, contentComplete, reviewResume } from "../../../lib/onboarding";
import { useApplicantProfile } from "../../../state/applicantProfileState";
import { useEditorState } from "../../../state/editorState";
import { EditorPage } from "../../editor/EditorPage";
import { StepFrame, type StepNav } from "../StepFrame";

/** Step 5: what was imported, what is worth fixing, and the full editor to fix it in. */
export function ContentStep({ nav }: { nav: StepNav }) {
  const editor = useEditorState();
  const { gaps } = useApplicantProfile();
  const review = reviewResume(editor.resume);

  return (
    <StepFrame
      title="Check your resume content"
      intro="Everything tailored later comes from here: your jobs, projects and their bullets. Fix anything the import missed."
      nav={nav}
      complete={contentComplete(review)}
      onSave={() => (editor.dirty ? editor.save() : Promise.resolve(true))}
      skipWarning={SKIP_WARNINGS.content}
      error={editor.dirty && editor.errors.length ? editor.errors[0] : null}
    >
      {review.entries > 0 && (
        <DataList
          items={[
            { label: "Entries", value: review.entries },
            { label: "Bullet points", value: review.bullets },
            ...review.sections.map((section) => ({ label: section.title, value: section.count })),
          ]}
          mono
        />
      )}
      {review.bullets === 0 && (
        <p className="text-sm text-attn">
          Add at least one job, project or activity with a bullet point below.
        </p>
      )}
      {review.warnings.length > 0 && (
        <ul className="list-disc space-y-1 pl-5 text-sm text-attn">
          {review.warnings.slice(0, 8).map((w) => (
            <li key={w}>{w}</li>
          ))}
          {review.warnings.length > 8 && <li>…and {review.warnings.length - 8} more.</li>}
        </ul>
      )}
      <ProfileGapBanner
        gaps={gaps.filter((gap) => gap.path === "/profile/resume")}
        onOpen={() => {
          const education = editor.resume?.sections.find((s) => s.kind === "education");
          if (education)
            document
              .getElementById(`resume-section-${education.id}`)
              ?.scrollIntoView({ block: "start" });
        }}
      />
      <div className="border-t border-line pt-4">
        <EditorPage showContact={false} embedded />
      </div>
    </StepFrame>
  );
}
