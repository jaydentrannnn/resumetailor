import { useEffect, useState } from "react";
import type { CoverLetter } from "../api";
import {
  coverLetterPreviewUrl,
  downloadPdfUrl,
  downloadUrl,
  previewUrl,
  regenerateCoverLetter,
} from "../api";
import { buttonClass } from "../lib/buttonClass";
import { ResultFrame } from "../pages/run/ResultFrame";
import { CoverLetterActionBar, CoverLetterDetails } from "./CoverLetterPanel";
import { SEGMENT_BASE, SEGMENT_OFF, SEGMENT_ON, SEGMENT_TRACK } from "./ui/Segmented";

type PreviewTab = "resume" | "cover";

type Props = {
  jobId: string;
  coverLetter?: CoverLetter | null;
  onCoverRegenerated: (letter: CoverLetter) => void;
  readOnly?: boolean;
  /** Bumped when the resume was re-rendered, so the preview is fetched fresh. */
  revision?: number;
  /** Inside the Tailor page's "Last result" tile: no box of its own. */
  embedded?: boolean;
};

/**
 * Tabbed documents section: tailored resume and optional cover letter.
 *
 * Only one PDF iframe mounts at a time — Chrome/Edge on Windows use a singleton PDF
 * plugin, so two embedded previews on one page often leaves one blank.
 */
export function DocumentsCard({
  jobId,
  coverLetter,
  onCoverRegenerated,
  readOnly = false,
  revision = 0,
  embedded = false,
}: Props) {
  const hasCoverLetter = Boolean(coverLetter);
  const hasCoverPdf = Boolean(coverLetter?.has_pdf);
  const [tab, setTab] = useState<PreviewTab>("resume");
  const [coverPreviewKey, setCoverPreviewKey] = useState(0);

  useEffect(() => {
    setTab("resume");
    setCoverPreviewKey(0);
  }, [jobId]);

  const resumeSrc = revision ? `${previewUrl(jobId)}?v=${revision}` : previewUrl(jobId);
  const coverSrc = coverLetterPreviewUrl(jobId, coverPreviewKey);
  const activeSrc = tab === "cover" && hasCoverPdf ? coverSrc : tab === "resume" ? resumeSrc : null;
  const activeTitle =
    tab === "cover" && hasCoverPdf ? "Cover letter preview" : "Tailored resume preview";

  async function handleCoverRegenerate(instruction: string) {
    const updated = await regenerateCoverLetter(jobId, instruction);
    onCoverRegenerated(updated);
    setCoverPreviewKey((key) => key + 1);
  }

  return (
    <ResultFrame embedded={embedded}>
      <div className="flex flex-wrap items-center justify-between gap-3">
        {hasCoverLetter ? (
          <div
            role="tablist"
            aria-label="Documents"
            className={SEGMENT_TRACK}
            onKeyDown={(e) => {
              /** Roving-tabindex arrow navigation, as `role="tablist"` promises. */
              if (e.key !== "ArrowLeft" && e.key !== "ArrowRight") return;
              e.preventDefault();
              const next = tab === "resume" ? "cover" : "resume";
              setTab(next);
              (
                e.currentTarget.querySelector(`#documents-tab-${next}`) as HTMLElement | null
              )?.focus();
            }}
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
        ) : embedded ? (
          <h3 className="rt-tile-title">Tailored resume</h3>
        ) : (
          <h2 className="rt-tile-title">Tailored resume</h2>
        )}
        {activeSrc && (
          <a
            href={activeSrc}
            target="_blank"
            rel="noreferrer"
            className="text-[13px] text-ink-muted underline underline-offset-2 hover:text-ink"
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
              <a href={downloadPdfUrl(jobId)} download className={buttonClass("primary", "sm")}>
                Download .pdf
              </a>
              <a href={downloadUrl(jobId)} download className={buttonClass("secondary", "sm")}>
                Download .docx
              </a>
            </div>
            <PdfFrame
              iframeKey={`resume-${jobId}-${revision}`}
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
              <PdfFrame iframeKey={`cover-${coverPreviewKey}`} title={activeTitle} src={coverSrc} />
            ) : (
              <p className="py-6 text-sm text-ink-muted">
                PDF preview is not available for this cover letter. Use the downloads above or the
                letter text below.
              </p>
            )}
            <CoverLetterDetails
              letter={coverLetter}
              onRegenerate={handleCoverRegenerate}
              readOnly={readOnly}
            />
          </>
        )}
      </div>
    </ResultFrame>
  );
}

function PdfFrame({ iframeKey, title, src }: { iframeKey: string; title: string; src: string }) {
  /**
   * Single embedded PDF viewer for the active document tab.
   *
   * `#toolbar=0&navpanes=0` hides Chrome's own PDF chrome (dark toolbar +
   * thumbnail rail) inside the embed — it's the viewer's UI, not this page's,
   * and at full chrome it was the single darkest, most alien element on an
   * otherwise cream/editorial page. "Open in new tab" (elsewhere on this card)
   * still points at the bare URL, so a real full viewer with its own
   * download/print controls is one click away.
   */
  return (
    <div className="overflow-hidden rounded-sm border border-line bg-sunken">
      <iframe
        key={iframeKey}
        title={title}
        src={`${src}#toolbar=0&navpanes=0`}
        className="h-[70vh] w-full bg-doc-preview"
      >
        <p className="p-4 text-sm text-ink-muted">
          PDF preview is not available in this browser.{" "}
          <a href={src} target="_blank" rel="noreferrer" className="rt-link">
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
      tabIndex={selected ? 0 : -1}
      onClick={onSelect}
      className={`${SEGMENT_BASE} ${selected ? SEGMENT_ON : SEGMENT_OFF}`}
    >
      {children}
    </button>
  );
}
