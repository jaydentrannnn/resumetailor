import type { ReactNode } from "react";
import { type Tone, toneChipClass } from "../../lib/tone";

/**
 * The mark half of a status: a small SVG whose shape is unique to the tone (check, ring,
 * diamond, spinner, dash, dot). `aria-hidden` — it is always paired with a text label, so
 * a status never depends on shape or colour alone. Inherits colour from its parent.
 */
export function StatusMark({ tone, className = "" }: { tone: Tone; className?: string }) {
  const common = {
    "aria-hidden": true as const,
    viewBox: "0 0 10 10",
    className: `size-2.5 shrink-0 ${className}`.trim(),
    fill: "none",
    stroke: "currentColor",
    strokeWidth: 1.7,
  };
  switch (tone) {
    case "done":
      return (
        <svg {...common}>
          <path d="M1.8 5.4 4 7.6l4.4-5.2" strokeLinecap="square" />
        </svg>
      );
    case "attention":
      return (
        <svg {...common}>
          <circle cx="5" cy="5" r="3.3" />
        </svg>
      );
    case "failed":
      return (
        <svg {...common} stroke="none" fill="currentColor">
          <path d="M5 1 9 5 5 9 1 5Z" />
        </svg>
      );
    case "live":
      return (
        <svg {...common} className={`${common.className} animate-spin motion-reduce:animate-none`}>
          <circle cx="5" cy="5" r="3.6" className="text-line-hover" stroke="currentColor" />
          <path d="M5 1.4a3.6 3.6 0 0 1 3.6 3.6" className="text-accent" stroke="currentColor" />
        </svg>
      );
    case "muted":
      return (
        <svg {...common}>
          <path d="M1.5 5h7" />
        </svg>
      );
    default:
      return (
        <svg {...common} stroke="none" fill="currentColor">
          <circle cx="5" cy="5" r="2.6" />
        </svg>
      );
  }
}

/**
 * A status chip: tinted pill, mark, then the label (always a word, never colour alone).
 * `mark={false}` drops the shape for a label that carries its own typed glyph.
 */
export function StatusChip({
  tone,
  children,
  className = "",
  mark = true,
}: {
  tone: Tone;
  children: ReactNode;
  className?: string;
  mark?: boolean;
}) {
  return (
    <span
      className={`inline-flex h-6 items-center gap-[7px] whitespace-nowrap rounded-sm px-[9px] text-xs font-medium ${toneChipClass(tone)} ${className}`.trim()}
    >
      {mark && <StatusMark tone={tone} />}
      {children}
    </span>
  );
}
