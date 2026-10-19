import { ProfileGapBanner } from "../../components/ProfileGapBanner";
import { Page } from "../../components/ui";
import { useApplicantProfile } from "../../state/applicantProfileState";
import { useEditorState } from "../../state/editorState";
import { EditorPage } from "../editor/EditorPage";

/**
 * Resume: the master resume every tailored resume draws from. Contact details live on
 * Profile › Personal information; both save to the same resume.
 */
export function ResumePage() {
  const applicant = useApplicantProfile();
  const editor = useEditorState();
  const education = editor.resume?.sections.find((section) => section.kind === "education");
  return (
    <Page className="pb-4">
      <ProfileGapBanner
        gaps={applicant.gaps.filter((gap) => gap.path === "/resume")}
        onOpen={() =>
          education &&
          document
            .getElementById(`resume-section-${education.id}`)
            ?.scrollIntoView({ block: "start" })
        }
      />
      <EditorPage showContact={false} />
    </Page>
  );
}
