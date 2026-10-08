/**
 * Status taxonomy shared by StatusMark/StatusChip and the header pills. Every tone has its
 * own hue, its own mark shape and (at the call site) a text label, so no status relies on
 * colour alone: done = check, attention = ring, failed = diamond, live = spinner,
 * muted = dash, neutral = dot, ready = green dot (actionable now, not yet done).
 */
export type Tone = "done" | "ready" | "attention" | "failed" | "live" | "neutral" | "muted";

/** Text colour (the mark inherits it via currentColor). */
export const TONE_TEXT: Record<Tone, string> = {
  done: "text-success",
  ready: "text-success",
  attention: "text-attn",
  failed: "text-danger",
  live: "text-ink-2",
  neutral: "text-ink-2",
  muted: "text-ink-muted",
};

/** Chip surface: a faint tint of the hue; live and muted are outlined instead of tinted. */
const TONE_SURFACE: Record<Tone, string> = {
  done: "bg-success-soft",
  ready: "bg-success-soft",
  attention: "bg-attn-soft",
  failed: "bg-danger-soft",
  live: "shadow-[inset_0_0_0_1px_var(--color-line-hover)]",
  neutral: "bg-ink/10",
  muted: "shadow-[inset_0_0_0_1px_var(--color-line)]",
};

/** Colour + surface classes for a chip-shaped element of the given tone. */
export function toneChipClass(tone: Tone): string {
  return `${TONE_TEXT[tone]} ${TONE_SURFACE[tone]}`;
}
