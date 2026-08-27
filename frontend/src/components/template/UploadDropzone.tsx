import { useRef, useState, type DragEvent } from "react";

type Props = {
  disabled?: boolean;
  onFile: (file: File) => void;
  label?: string;
};

const DOCX_MIME =
  "application/vnd.openxmlformats-officedocument.wordprocessingml.document";

function isDocx(file: File): boolean {
  return file.name.toLowerCase().endsWith(".docx") || file.type === DOCX_MIME;
}

/**
 * Drag/drop + file picker for a single .docx baseline export.
 */
export function UploadDropzone({ disabled, onFile, label }: Props) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);
  const [rejected, setRejected] = useState(false);

  function accept(file: File | null) {
    /** Forward a valid .docx to the caller; flag anything else instead of silently
     * handing it to the analyzer, which would just fail deeper with a less clear error. */
    if (!file) return;
    if (!isDocx(file)) {
      setRejected(true);
      return;
    }
    setRejected(false);
    onFile(file);
  }

  function onDrop(e: DragEvent<HTMLDivElement>) {
    /** Accept a dropped .docx from the drag target. */
    e.preventDefault();
    setDragging(false);
    if (disabled) return;
    accept(e.dataTransfer.files?.[0] ?? null);
  }

  return (
    <div
      onDragEnter={(e) => {
        e.preventDefault();
        if (!disabled) setDragging(true);
      }}
      onDragOver={(e) => e.preventDefault()}
      onDragLeave={() => setDragging(false)}
      onDrop={onDrop}
      className={`mt-4 flex flex-col items-center justify-center gap-3 rounded-lg border-2 border-dashed px-6 py-10 transition ${
        dragging
          ? "border-accent bg-accent-soft/60"
          : "border-line bg-paper/40 hover:border-accent/60"
      }`}
    >
      <p className="text-sm text-ink-muted">
        {label ?? (disabled ? "Working…" : "Drop a .docx here, or")}
      </p>
      <button
        type="button"
        disabled={disabled}
        onClick={() => inputRef.current?.click()}
        className="rounded-lg bg-accent px-4 py-2.5 text-sm font-semibold text-on-accent disabled:opacity-50"
      >
        {disabled ? "Working…" : "Choose file"}
      </button>
      {rejected && (
        <p className="text-xs text-danger">That isn't a .docx file — try again.</p>
      )}
      <input
        ref={inputRef}
        type="file"
        accept=".docx,application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        className="hidden"
        onChange={(e) => {
          accept(e.target.files?.[0] ?? null);
          e.target.value = "";
        }}
      />
    </div>
  );
}
