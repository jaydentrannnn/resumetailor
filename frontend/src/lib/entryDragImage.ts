/** Give the browser a compact entry card instead of a drag-handle bitmap. */
export function setEntryDragImage(
  handle: HTMLElement,
  transfer: DataTransfer,
  clientX: number,
  clientY: number,
): () => void {
  const card = handle.closest<HTMLElement>("[data-resume-entry]");
  const summary = card?.querySelector<HTMLElement>("[data-entry-summary]");
  if (!card || !summary) return () => {};
  const bounds = card.getBoundingClientRect();
  const preview = document.createElement("div");
  preview.dataset.entryDragPreview = "";
  preview.setAttribute("aria-hidden", "true");
  preview.inert = true;
  preview.className =
    "pointer-events-none fixed rounded-sm border border-line bg-panel px-3 py-4 text-ink shadow-lg";
  preview.style.left = "-10000px";
  preview.style.top = "0";
  preview.style.width = `${bounds.width}px`;
  const copy = summary.cloneNode(true) as HTMLElement;
  // Keep only the summary: an expanded editor would hide the drop destination.
  for (const node of copy.querySelectorAll<HTMLElement>("[id], [aria-controls]")) {
    node.removeAttribute("id");
    node.removeAttribute("aria-controls");
  }
  preview.append(copy);
  document.body.append(preview);
  transfer.setDragImage(
    preview,
    Math.max(0, clientX - bounds.left),
    Math.max(0, clientY - bounds.top),
  );
  return () => preview.remove();
}
