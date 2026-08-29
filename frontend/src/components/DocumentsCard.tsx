import { useEffect, useState } from "react";
import type { CoverLetter } from "../api";
import {
  coverLetterPreviewUrl,
  downloadPdfUrl,
  downloadUrl,
  previewUrl,
  regenerateCoverLetter,
} from "../api";
import { CoverLetterActionBar, CoverLetterDetails } from "./CoverLetterPanel";

type PreviewTab = "resume" | "cover";

type Props = {
  jobId: string;
  coverLetter?: CoverLetter | null;
  onCoverRegenerated: (letter: CoverLetter) => void;
};

/**
 * Tabbed documents section: tailored resume and optional cover letter.
 *
 * Only one PDF iframe mounts at a time — Chrome/Edge on Windows use a singleton PDF
 * plugin, so two embedded previews on one page often leaves one blank.
 */
export function DocumentsCard({ jobId, coverLetter, onCoverRegenerated }: Props) {
  const hasCoverLetter = Boolean(coverLetter);
  const hasCoverPdf = Boolean(coverLetter?.has_pdf);
  const [tab, setTab] = useState<PreviewTab>("resume");
  const [coverPreviewKey, setCoverPreviewKey] = useState(0);

  useEffect(() => {
    setTab("resume");
    setCoverPreviewKey(0);
  }, [jobId]);

  const resumeSrc = previewUrl(jobId);
  const coverSrc = coverLetterPreviewUrl(jobId, coverPreviewKey);
  const activeSrc =
    tab === "cover" && hasCoverPdf ? coverSrc : tab === "resume" ? resumeSrc : null;
  const activeTitle =
    tab === "cover" && hasCoverPdf ? "Cover letter preview" : "Tailored resume preview";

  async function handleCoverRegenerate(instruction: string) {
    const updated = await regenerateCoverLetter(jobId, instruction);
    onCoverRegenerated(updated);
    setCoverPreviewKey((key) => key + 1);
  }

  return (
    <section className="rounded-xl border border-line bg-panel p-5 shadow-sm">
      <div className="flex flex-wrap items-center justify-between gap-3">
        {hasCoverLetter ? (
          <div
            role="tablist"
            aria-label="Documents"
            className="flex flex-wrap gap-2"
          >
            <PreviewTabButton
              id="documents-tab-resume"
              panelId="documents-panel"
              selected={tab === "resume"}
              onSelect={() => setTab("resume")}
            >
              Tailored resume
            </PreviewTabButton>
            <PreviewTabButton
              id="documents-tab-cover"
              panelId="documents-panel"
              selected={tab === "cover"}
              onSelect={() => setTab("cover")}
            >
              Cover letter
            </PreviewTabButton>
          </div>
        ) : (
          <h2 className="font-display text-xl font-semibold">Tailored resume</h2>
        )}
        {activeSrc && (
          <a
            href={activeSrc}
            target="_blank"
            rel="noreferrer"
            className="text-sm text-ink-muted underline-offset-2 hover:text-accent hover:underline"
          >
            Open in new tab
          </a>
        )}
      </div>

      <div
        id="documents-panel"
        role="tabpanel"
        aria-labelledby={
          tab === "cover" && hasCoverLetter ? "documents-tab-cover" : "documents-tab-resume"
        }
        className="mt-4"
      >
        {tab === "resume" && (
          <>
            <div className="mb-4 flex flex-wrap justify-end gap-2">
              <a
                href={downloadPdfUrl(jobId)}
                className="rounded-md bg-accent px-3 py-1.5 text-sm font-medium text-on-accent"
              >
                Download .pdf
              </a>
              <a
                href={downloadUrl(jobId)}
                className="rounded-md border border-line px-3 py-1.5 text-sm font-medium text-ink hover:border-accent hover:text-accent"
              >
                Download .docx
              </a>
            </div>
            <PdfFrame
              iframeKey={`resume-${jobId}`}
              title={activeTitle}
              src={resumeSrc}
            />
          </>
        )}

        {tab === "cover" && coverLetter && (
          <>
            <div className="mb-4">
              <CoverLetterActionBar letter={coverLetter} jobId={jobId} />
            </div>
            {hasCoverPdf ? (
              <PdfFrame
                iframeKey={`cover-${coverPreviewKey}`}
                title={activeTitle}
                src={coverSrc}
              />
            ) : (
              <p className="rounded-lg border border-line bg-paper/40 px-4 py-6 text-sm text-ink-muted">
                PDF preview is not available for this cover letter. Use the downloads above
                or the letter text below.
              </p>
            )}
            <CoverLetterDetails
              letter={coverLetter}
              onRegenerate={handleCoverRegenerate}
            />
          </>
        )}
      </div>
    </section>
  );
}

function PdfFrame({
  iframeKey,
  title,
  src,
}: {
  iframeKey: string;
  title: string;
  src: string;
}) {
  /** Single embedded PDF viewer for the active document tab. */
  return (
    <div className="overflow-hidden rounded-lg border border-line bg-paper/40">
      <iframe key={iframeKey} title={title} src={src} className="h-[70vh] w-full bg-white">
        <p className="p-4 text-sm text-ink-muted">
          PDF preview is not available in this browser.{" "}
          <a href={src} target="_blank" rel="noreferrer" className="text-accent underline">
            Open the PDF in a new tab
          </a>
          .
        </p>
      </iframe>
    </div>
  );
}

function PreviewTabButton({
  id,
  panelId,
  selected,
  onSelect,
  children,
}: {
  id: string;
  panelId: string;
  selected: boolean;
  onSelect: () => void;
  children: string;
}) {
  /** One documents tab; only the selected tab's iframe is mounted in the parent. */
  return (
    <button
      type="button"
      role="tab"
      id={id}
      aria-selected={selected}
      aria-controls={panelId}
      onClick={onSelect}
      className={
        selected
          ? "rounded-lg bg-accent px-3 py-1.5 text-sm font-semibold text-on-accent"
          : "rounded-lg border border-line px-3 py-1.5 text-sm font-medium text-ink-muted hover:bg-paper"
      }
    >
      {children}
    </button>
  );
}
