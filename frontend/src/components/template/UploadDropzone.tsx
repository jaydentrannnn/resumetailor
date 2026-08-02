import { useCallback, useRef, useState, type DragEvent } from "react";

type Props = {
  disabled?: boolean;
  onFile: (file: File) => void;
  label?: string;
};

/**
 * Drag/drop + file picker for a single .docx baseline export.
 */
export function UploadDropzone({ disabled, onFile, label }: Props) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);

  const onDrop = useCallback(
    (e: DragEvent<HTMLDivElement>) => {
      /** Accept a dropped .docx from the drag target. */
      e.preventDefault();
      setDragging(false);
      const file = e.dataTransfer.files?.[0] ?? null;
      if (file) onFile(file);
    },
    [onFile],
  );

  return (
    <div
      onDragEnter={(e) => {
        e.preventDefault();
        setDragging(true);
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
        className="rounded-lg bg-accent px-4 py-2.5 text-sm font-semibold text-white disabled:opacity-50"
      >
        {disabled ? "Working…" : "Choose file"}
      </button>
      <input
        ref={inputRef}
        type="file"
        accept=".docx,application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        className="hidden"
        onChange={(e) => {
          const file = e.target.files?.[0] ?? null;
          if (file) onFile(file);
          e.target.value = "";
        }}
      />
    </div>
  );
}
