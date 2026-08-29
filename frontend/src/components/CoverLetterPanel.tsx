import { useState } from "react";
import type { CoverLetter } from "../api";
import {
  coverLetterDocxUrl,
  coverLetterMdUrl,
  coverLetterPdfUrl,
} from "../api";
import { CopyButton } from "./CopyButton";

export function letterText(letter: CoverLetter): string {
  /** Full letter body for copy-all, excluding letterhead the .docx already carries. */
  const blocks = [
    letter.date,
    ...letter.inside_address,
    "",
    letter.salutation,
    "",
    ...letter.paragraphs,
    "",
    letter.closing,
    letter.signature,
  ];
  return blocks.filter((line, i, arr) => line !== "" || (i > 0 && arr[i - 1] !== "")).join("\n");
}

type ActionProps = {
  letter: CoverLetter;
  jobId: string;
};

export function CoverLetterActionBar({ letter, jobId }: ActionProps) {
  /** Download and copy controls for the cover letter tab. */
  return (
    <div className="flex flex-wrap items-center justify-between gap-3">
      <p className="text-sm text-ink-muted">
        {letter.word_count} words · model {letter.model || "—"}
      </p>
      <div className="flex flex-wrap justify-end gap-2">
        <CopyButton label="Copy all" text={letterText(letter)} />
        <a
          href={coverLetterMdUrl(jobId)}
          className="rounded-lg border border-line px-3 py-1.5 text-sm hover:bg-paper"
        >
          Download .md
        </a>
        {letter.has_docx && (
          <a
            href={coverLetterDocxUrl(jobId)}
            className="rounded-lg border border-line px-3 py-1.5 text-sm hover:bg-paper"
          >
            Download .docx
          </a>
        )}
        {letter.has_pdf && (
          <a
            href={coverLetterPdfUrl(jobId)}
            className="rounded-lg border border-line px-3 py-1.5 text-sm hover:bg-paper"
          >
            Download .pdf
          </a>
        )}
      </div>
    </div>
  );
}

type DetailsProps = {
  letter: CoverLetter;
  onRegenerate: (instruction: string) => Promise<void>;
};

export function CoverLetterDetails({ letter, onRegenerate }: DetailsProps) {
  /** Warnings, letter text, and regenerate controls below the PDF preview. */
  const [instruction, setInstruction] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleRegenerate() {
    setBusy(true);
    setError(null);
    try {
      await onRegenerate(instruction);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Regeneration failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="mt-4 space-y-4 border-t border-line pt-4">
      {letter.warnings.length > 0 && (
        <ul className="list-disc space-y-1 pl-5 text-sm text-warning">
          {letter.warnings.map((warning) => (
            <li key={warning}>{warning}</li>
          ))}
        </ul>
      )}

      <div className="space-y-4 text-sm leading-relaxed">
        {letter.paragraphs.map((para, index) => (
          <p key={`${index}-${para.slice(0, 24)}`}>{para}</p>
        ))}
      </div>

      <div className="space-y-2">
        <label className="block text-sm font-medium" htmlFor="cover-regen-instruction">
          Regenerate with instruction (optional)
        </label>
        <textarea
          id="cover-regen-instruction"
          value={instruction}
          onChange={(e) => setInstruction(e.target.value)}
          rows={3}
          className="field w-full font-mono text-sm"
          placeholder="e.g. Lead with the RAG project and shorten the close."
        />
        {error && <p className="text-sm text-danger">{error}</p>}
        <button
          type="button"
          disabled={busy}
          onClick={() => void handleRegenerate()}
          className="rounded-lg border border-line px-3 py-2 text-sm font-medium hover:bg-paper disabled:opacity-50"
        >
          {busy ? "Regenerating…" : "Regenerate cover letter"}
        </button>
      </div>
    </div>
  );
}
