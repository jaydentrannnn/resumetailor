import { useState } from "react";
import { type DesktopSaveResult, openJobFile, revealJobFile, saveFileAs } from "../api";
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
  /** Desktop: save some other way than fetching `url` and sending it back (a large
   * file the server can write itself). */
  desktopSave?: () => Promise<DesktopSaveResult>;
};

/** Run a desktop save, saying how it went. */
function useReportSave(): (save: () => Promise<DesktopSaveResult>) => Promise<void> {
  const toast = useToast();
  return async (save) => {
    try {
      const result = await save();
      if (result.saved) toast.success("Saved", result.path ?? undefined);
    } catch (err) {
      toast.error("Could not save the file", describe(err).detail);
    }
  };
}

/** Save a download through the native Save dialog (desktop app), saying how it went. */
export function useSaveFile(): (url: string, fallbackName: string) => Promise<void> {
  const report = useReportSave();
  return (url, fallbackName) => report(() => saveFileAs(url, fallbackName));
}

/**
 * Save a file the way this host does (the native Save dialog in the desktop app, a
 * download in the browser), for actions that are not a button, such as Ctrl+K.
 */
export function useSaveOrDownload(): {
  desktop: boolean;
  save: (url: string, fallbackName: string) => void;
} {
  const desktop = useDesktop();
  const saveFile = useSaveFile();
  return {
    desktop,
    save: (url, fallbackName) => {
      if (desktop) return void saveFile(url, fallbackName);
      const link = document.createElement("a");
      link.href = url;
      link.download = "";
      link.click();
    },
  };
}

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
  desktopSave,
}: SaveProps) {
  const desktop = useDesktop();
  const report = useReportSave();
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
    await report(desktopSave ?? (() => saveFileAs(url, fallbackName)));
    setBusy(false);
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
