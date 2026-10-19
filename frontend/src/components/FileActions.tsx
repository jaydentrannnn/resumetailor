import { useState } from "react";
import { openJobFile, revealJobFile, saveFileAs } from "../api";
import { type ButtonSize, type ButtonVariant, buttonClass } from "../lib/buttonClass";
import { describe } from "../lib/errors";
import { type JobFileKind, openLabel, saveLabel } from "../lib/fileActions";
import { useToast } from "../lib/toast";
import { useDesktop } from "../lib/useDesktop";
import { Button } from "./ui";

type SaveProps = {
  url: string;
  /** What the file is, for the label: "PDF" → "Save PDF…" / "Download PDF". */
  what: string;
  /** Used when the response names no file. */
  fallbackName: string;
  variant?: ButtonVariant;
  size?: ButtonSize;
  className?: string;
};

/**
 * Desktop: Save X… through the native Save dialog. Browser: a plain download link.
 */
export function SaveFileButton({
  url,
  what,
  fallbackName,
  variant = "secondary",
  size = "sm",
  className = "",
}: SaveProps) {
  const desktop = useDesktop();
  const toast = useToast();
  const [busy, setBusy] = useState(false);
  const label = saveLabel(what, desktop);

  if (!desktop)
    return (
      <a href={url} download className={buttonClass(variant, size, className)}>
        {label}
      </a>
    );

  async function save() {
    setBusy(true);
    try {
      const result = await saveFileAs(url, fallbackName);
      if (result.saved) toast.success("Saved", result.path ?? undefined);
    } catch (err) {
      toast.error("Could not save the file", describe(err).detail);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Button
      variant={variant}
      size={size}
      className={className}
      loading={busy}
      onClick={() => void save()}
    >
      {label}
    </Button>
  );
}

/** Desktop only: Show in folder and Open / Open in Word for one of a run's files. */
export function JobFileActions({ jobId, kind }: { jobId: string; kind: JobFileKind }) {
  const desktop = useDesktop();
  const toast = useToast();
  if (!desktop) return null;

  function act(run: () => Promise<void>, failure: string) {
    run().catch((err) => toast.error(failure, describe(err).detail));
  }

  return (
    <>
      <Button
        variant="plain"
        size="sm"
        onClick={() => act(() => revealJobFile(jobId, kind), "Could not show the file")}
      >
        Show in folder
      </Button>
      <Button
        variant="plain"
        size="sm"
        onClick={() => act(() => openJobFile(jobId, kind), "Could not open the file")}
      >
        {openLabel(kind)}
      </Button>
    </>
  );
}

/**
 * Link that opens a document on its own: a new tab in the browser, an app window on
 * desktop (the shell keeps local pages in the app).
 */
export function OpenDocumentLink({
  href,
  className = "rt-link",
}: {
  href: string;
  className?: string;
}) {
  const desktop = useDesktop();
  return (
    <a href={href} target="_blank" rel="noreferrer" className={className}>
      {desktop ? "Open in window" : "Open in new tab"}
    </a>
  );
}
