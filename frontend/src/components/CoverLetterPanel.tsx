import { useState } from "react";
import type { CoverLetter } from "../api";
import { buttonClass } from "../lib/buttonClass";

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

/** What the cover-letter guard flagged; nothing when it flagged nothing. */
export function CoverLetterWarnings({
  letter,
  titled = false,
}: {
  letter: CoverLetter;
  /** Say whose warnings they are (shown away from the letter's own details). */
  titled?: boolean;
}) {
  if (!letter.warnings.length) return null;
  return (
    <div className="space-y-1">
      {titled && <p className="text-xs font-medium text-ink-2">Cover letter warnings</p>}
      <ul className="list-disc space-y-1 pl-5 text-sm text-attn">
        {letter.warnings.map((warning) => (
          <li key={warning}>{warning}</li>
        ))}
      </ul>
    </div>
  );
}

type DetailsProps = {
  letter: CoverLetter;
  onRegenerate: (instruction: string) => Promise<void>;
  readOnly?: boolean;
};

export function CoverLetterDetails({ letter, onRegenerate, readOnly = false }: DetailsProps) {
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
    <div className="space-y-4">
      <p className="text-xs text-ink-muted">
        <span className="font-mono tabular-nums">{letter.word_count}</span> words · model{" "}
        <span className="font-mono">{letter.model || "—"}</span>
      </p>
      <CoverLetterWarnings letter={letter} />

      <div className="space-y-4 text-sm leading-relaxed">
        {letter.paragraphs.map((para, index) => (
          <p key={`${index}-${para.slice(0, 24)}`}>{para}</p>
        ))}
      </div>

      {!readOnly && (
        <div className="space-y-2">
          <label className="block text-xs font-medium text-ink-2" htmlFor="cover-regen-instruction">
            Regenerate with instruction (optional)
          </label>
          <textarea
            id="cover-regen-instruction"
            value={instruction}
            onChange={(e) => setInstruction(e.target.value)}
            rows={3}
            className="field font-mono text-sm"
            placeholder="e.g. Lead with the RAG project and shorten the close."
          />
          {error && <p className="text-sm text-danger">{error}</p>}
          <button
            type="button"
            disabled={busy}
            onClick={() => void handleRegenerate()}
            className={buttonClass("secondary", "md")}
          >
            {busy ? "Regenerating…" : "Regenerate cover letter"}
          </button>
        </div>
      )}
    </div>
  );
}
