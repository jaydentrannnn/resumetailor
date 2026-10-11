import { useEffect, useRef, useState, type ReactNode } from "react";

/** Commit a date only when leaving its control; partial typing must not move the row. */
export function BufferedField({
  value,
  onChange,
  children,
}: {
  value: string;
  onChange: (value: string) => void;
  children: (value: string, setValue: (value: string) => void) => ReactNode;
}) {
  const [draft, setDraft] = useState(value);
  const focused = useRef(false);
  useEffect(() => {
    if (!focused.current) setDraft(value);
  }, [value]);
  return (
    <div
      onFocus={() => {
        focused.current = true;
      }}
      onBlur={(event) => {
        if (event.currentTarget.contains(event.relatedTarget as Node | null)) return;
        focused.current = false;
        if (draft !== value) onChange(draft);
      }}
    >
      {children(draft, setDraft)}
    </div>
  );
}
