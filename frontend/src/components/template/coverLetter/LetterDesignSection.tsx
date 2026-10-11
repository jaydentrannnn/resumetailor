import { useState } from "react";
import { COVER_STARTER_URL, type CoverLetterSettings } from "../../../api";
import { describe } from "../../../lib/errors";
import { useConfirm } from "../../../state/confirmState";
import { Button, buttonClass, Segmented } from "../../ui";
import { UploadDropzone } from "../UploadDropzone";

const DESIGNS = [
  { id: "generated", label: "From my resume template" },
  { id: "own", label: "My own letter" },
];

/**
 * Where the letter's design comes from: built from the resume template, or a letter the
 * person uploaded with «fields» where the words go. Uploading and removing take effect
 * at once; choosing between them is part of the draft.
 */
export function LetterDesignSection({
  settings,
  ownLetter,
  onChange,
  onUpload,
  onRemove,
}: {
  settings: CoverLetterSettings;
  ownLetter: boolean;
  onChange: (next: CoverLetterSettings) => void;
  /** Returns the letter's problems, [] when it was accepted. */
  onUpload: (file: File) => Promise<string[]>;
  onRemove: () => Promise<void>;
}) {
  const [busy, setBusy] = useState(false);
  const [problems, setProblems] = useState<string[]>([]);
  const { confirm } = useConfirm();
  const own = settings.design === "own";

  const upload = async (file: File) => {
    setBusy(true);
    setProblems([]);
    try {
      const found = await onUpload(file);
      setProblems(found);
      if (!found.length) onChange({ ...settings, design: "own" });
    } catch (reason) {
      setProblems([describe(reason).detail]);
    } finally {
      setBusy(false);
    }
  };

  const remove = async () => {
    const ok = await confirm({
      title: "Remove your own letter?",
      message: "Cover letters are built from your resume template again.",
      confirmLabel: "Remove",
      tone: "danger",
    });
    if (!ok) return;
    setBusy(true);
    try {
      await onRemove();
      onChange({ ...settings, design: "generated" });
    } finally {
      setBusy(false);
    }
  };

  return (
    <section aria-labelledby="cover-design">
      <h3 id="cover-design" className="font-semibold">
        Letter design
      </h3>
      <Segmented
        className="mt-2"
        label="Letter design"
        items={DESIGNS}
        value={own ? "own" : "generated"}
        onChange={(id) => onChange({ ...settings, design: id as "generated" | "own" })}
      />
      {own && (
        <div className="mt-3 space-y-3">
          <p className="text-ink-muted">
            Start from your current letter: download it with «fields» in place of the words, restyle
            it in Word (keep «Body» on its own line), then upload it. Your letter&apos;s fields
            decide the letterhead.
          </p>
          <a className={buttonClass("plain", "sm")} href={COVER_STARTER_URL} download>
            Download starter letter
          </a>
          {ownLetter && (
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-ink">Your letter is uploaded.</span>
              <Button variant="danger" size="sm" disabled={busy} onClick={() => void remove()}>
                Remove
              </Button>
            </div>
          )}
          <UploadDropzone
            disabled={busy}
            label={ownLetter ? "Replace your letter" : "Upload your letter"}
            onFile={(file) => void upload(file)}
          />
          {problems.length > 0 && (
            <ul className="list-disc space-y-1 pl-5 text-danger" role="alert">
              {problems.map((problem) => (
                <li key={problem}>{problem}</li>
              ))}
            </ul>
          )}
        </div>
      )}
    </section>
  );
}
