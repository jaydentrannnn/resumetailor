import { useEffect, useState } from "react";
import type { CoverLetter } from "../api";
import {
  coverLetterDocxUrl,
  coverLetterMdUrl,
  coverLetterPdfUrl,
  coverLetterPreviewUrl,
  downloadPdfUrl,
  downloadUrl,
  previewUrl,
  regenerateCoverLetter,
} from "../api";
import { CopyButton } from "./CopyButton";
import { CoverLetterDetails, CoverLetterWarnings, letterText } from "./CoverLetterPanel";
import type { Command } from "../lib/commands";
import { saveLabel } from "../lib/fileActions";
import { useCommands } from "../state/commandState";
import { JobFileActions, SaveFileButton, useSaveOrDownload } from "./FileActions";
import { DocumentViewer, type ViewerDoc } from "./viewer/DocumentViewer";

type Props = {
  jobId: string;
  coverLetter?: CoverLetter | null;
  onCoverRegenerated: (letter: CoverLetter) => void;
  readOnly?: boolean;
  /** Bumped when the resume was re-rendered, so the preview is fetched fresh. */
  revision?: number;
  /** Bumped when the cover letter was regenerated elsewhere. */
  coverRevision?: number;
  /** Show the letter's text and regenerate controls under the viewer (the Tailor page
   * keeps them in its Content tab instead). Without them, the letter's warnings still
   * show, over the viewer. */
  coverDetails?: boolean;
  /** Height of the document area. */
  viewerClassName?: string;
};

/**
 * A run's documents in the shared viewer: the tailored resume and, when there is one,
 * the cover letter, each with its Save / Show in folder / Open actions.
 */
export function DocumentsCard({
  jobId,
  coverLetter,
  onCoverRegenerated,
  readOnly = false,
  revision = 0,
  coverRevision = 0,
  coverDetails = true,
  viewerClassName,
}: Props) {
  const [tab, setTab] = useState("resume");
  const [coverKey, setCoverKey] = useState(0);
  useEffect(() => {
    setTab("resume");
    setCoverKey(0);
  }, [jobId]);

  const docs: ViewerDoc[] = [
    {
      id: "resume",
      label: "Resume",
      src: revision ? `${previewUrl(jobId)}?v=${revision}` : previewUrl(jobId),
      actions: (
        <>
          <JobFileActions jobId={jobId} kind="resume-docx" />
          <SaveFileButton
            url={downloadUrl(jobId)}
            what="Word"
            fallbackName="resume.docx"
            variant="plain"
          />
          <SaveFileButton
            url={downloadPdfUrl(jobId)}
            what="PDF"
            fallbackName="resume.pdf"
            variant="primary"
          />
        </>
      ),
    },
  ];
  if (coverLetter)
    docs.push({
      id: "cover",
      label: "Cover letter",
      src: coverLetter.has_pdf ? coverLetterPreviewUrl(jobId, coverKey + coverRevision) : null,
      empty: "PDF preview is not available for this cover letter. Save it as Word or text.",
      actions: (
        <>
          <CopyButton label="Copy text" text={letterText(coverLetter)} />
          {coverLetter.has_docx && <JobFileActions jobId={jobId} kind="cover-docx" />}
          <SaveFileButton
            url={coverLetterMdUrl(jobId)}
            what="text"
            fallbackName="cover_letter.md"
            variant="plain"
          />
          {coverLetter.has_docx && (
            <SaveFileButton
              url={coverLetterDocxUrl(jobId)}
              what="Word"
              fallbackName="cover_letter.docx"
              variant="plain"
            />
          )}
          {coverLetter.has_pdf && (
            <SaveFileButton
              url={coverLetterPdfUrl(jobId)}
              what="PDF"
              fallbackName="cover_letter.pdf"
              variant="primary"
            />
          )}
        </>
      ),
    });

  const { desktop, save } = useSaveOrDownload();
  useCommands((): Command[] => {
    const file = (id: string, what: string, url: string, name: string): Command => ({
      id,
      title: saveLabel(what, desktop),
      group: "Document",
      keywords: "save download export",
      run: () => save(url, name),
    });
    const commands = [
      file("doc-resume-pdf", "resume PDF", downloadPdfUrl(jobId), "resume.pdf"),
      file("doc-resume-docx", "resume Word file", downloadUrl(jobId), "resume.docx"),
    ];
    if (!coverLetter) return commands;
    if (coverLetter.has_pdf)
      commands.push(
        file("doc-cover-pdf", "cover letter PDF", coverLetterPdfUrl(jobId), "cover_letter.pdf"),
      );
    if (coverLetter.has_docx)
      commands.push(
        file(
          "doc-cover-docx",
          "cover letter Word file",
          coverLetterDocxUrl(jobId),
          "cover_letter.docx",
        ),
      );
    const show = (id: string, title: string): Command => ({
      id: `doc-show-${id}`,
      title,
      group: "Document",
      disabled: tab === id,
      run: () => setTab(id),
    });
    return [show("resume", "Show the resume"), show("cover", "Show the cover letter"), ...commands];
  });

  async function regenerate(instruction: string) {
    const updated = await regenerateCoverLetter(jobId, instruction);
    onCoverRegenerated(updated);
    setCoverKey((key) => key + 1);
  }

  return (
    <div className="space-y-4">
      {!coverDetails && coverLetter && <CoverLetterWarnings letter={coverLetter} titled />}
      <DocumentViewer
        label="Documents"
        docs={docs}
        active={tab}
        onActive={setTab}
        frameKey={`${jobId}-${revision}`}
        className={viewerClassName}
      />
      {coverDetails && tab === "cover" && coverLetter && (
        <CoverLetterDetails letter={coverLetter} onRegenerate={regenerate} readOnly={readOnly} />
      )}
    </div>
  );
}
