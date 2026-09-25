import { useRef, useState } from "react";
import { deleteTranscript, uploadTranscript, type ApplicantProfileResponse } from "../../api";
import { Button } from "../../components/ui";
import { describe } from "../../lib/errors";
import { changedKeys } from "../../lib/profileForm";
import { useApplicantProfile } from "../../state/applicantProfileState";

const MAX_BYTES = 10 * 1024 * 1024;

/**
 * Unofficial transcript for forms with a transcript upload. The server saves the file and
 * the profile together, so unsaved edits elsewhere on the page are carried over on top.
 */
export function TranscriptUpload() {
  const applicant = useApplicantProfile();
  const input = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const hasTranscript = !!applicant.saved?.transcript_path;

  function adopt(result: ApplicantProfileResponse) {
    const { saved, draft } = applicant;
    const edits = changedKeys(saved, draft).filter((key) => key !== "transcript_path");
    applicant.accept(result);
    if (draft && edits.length)
      applicant.setDraft({
        ...result.profile,
        ...Object.fromEntries(edits.map((key) => [key, draft[key]])),
      });
  }

  async function run(action: () => Promise<ApplicantProfileResponse>) {
    setBusy(true);
    setError(null);
    try {
      adopt(await action());
    } catch (reason) {
      setError(describe(reason).detail || describe(reason).title);
    } finally {
      setBusy(false);
    }
  }

  function pick(file: File | undefined) {
    if (!file) return;
    if (!/\.pdf$/i.test(file.name) && file.type !== "application/pdf")
      setError("Upload a PDF file.");
    else if (file.size > MAX_BYTES) setError("That file is over 10 MB.");
    else void run(() => uploadTranscript(file));
    if (input.current) input.current.value = "";
  }

  return (
    <div id="profile-field-transcript_path" className="text-sm sm:col-span-2">
      <p className="font-medium">Transcript (PDF)</p>
      <p className="text-xs text-ink-muted">
        Uploaded only when a form has a transcript field. Unofficial transcripts are usually fine.
      </p>
      <div className="mt-2 flex flex-wrap items-center gap-2">
        {hasTranscript && (
          <span className="rounded-md bg-accent-soft px-2 py-1 text-xs text-accent">
            transcript.pdf saved
          </span>
        )}
        <input
          ref={input}
          type="file"
          accept="application/pdf,.pdf"
          className="sr-only"
          aria-label="Choose transcript PDF"
          onChange={(e) => pick(e.target.files?.[0])}
        />
        <Button size="sm" loading={busy} onClick={() => input.current?.click()}>
          {hasTranscript ? "Replace" : "Upload transcript"}
        </Button>
        {hasTranscript && (
          <Button
            size="sm"
            variant="ghost"
            disabled={busy}
            onClick={() => void run(deleteTranscript)}
          >
            Remove
          </Button>
        )}
      </div>
      {error && (
        <p role="alert" className="mt-1 text-xs text-danger">
          {error}
        </p>
      )}
    </div>
  );
}
