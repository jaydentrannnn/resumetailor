import type { TemplateEditStatus } from "../api";

function savedLabel(iso: string | null): string {
  if (!iso) return "";
  try {
    return new Date(iso).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
  } catch {
    return iso;
  }
}

/** What the session is waiting for, in one or two sentences. */
export function sessionMessage(status: TemplateEditStatus): string {
  if (!status.active)
    return "Change fonts, spacing, margins or where each field sits in Word, then review it here.";
  if (status.changed)
    return `Saved at ${savedLabel(status.saved_at)}. Review the changes, then install them as a new template.${
      status.editor_open ? " You can keep Word open and save again." : ""
    }`;
  if (status.editor_closed) return "Word was closed without saving. Open it again, or discard.";
  return status.editor_open
    ? "Open in Word. Save the file when you're done — this page notices the save."
    : "Waiting for the layout file to open. If it didn't, open it again.";
}
