export type ButtonVariant =
  "primary" | "secondary" | "plain" | "attention" | "success" | "danger" | "ghost";

// Three levels, no outlines. Solid: ink for a tile's one main action (`primary`,
// `secondary`), green for the step that moves an application forward (`success`, Fill).
// Tinted: a colour wash for steps that need a decision (`attention`: needs you, tailor
// again) or that failed or discard (`danger`). Plain: grey a step off the tile for
// housekeeping and navigation (pagination, Columns, View, Archive, Save beside an input).
const INK = "bg-primary font-medium text-on-primary hover:bg-primary/85";
export const PLAIN = "bg-plain font-medium text-ink hover:bg-plain-hover";
const VARIANT: Record<ButtonVariant, string> = {
  primary: INK,
  secondary: INK,
  success: "bg-accent font-medium text-on-accent hover:bg-accent/85",
  attention: "bg-attn-tint font-medium text-attn hover:bg-attn-tint-hover",
  danger: "bg-danger-tint font-medium text-danger hover:bg-danger-tint-hover",
  plain: PLAIN,
  ghost: "font-medium text-ink-muted hover:bg-sunken hover:text-ink",
};

const SIZE = {
  sm: "px-3 py-1.5 text-xs",
  md: "px-4 py-2 text-[13px]",
  lg: "px-4 py-3 text-sm",
  xl: "h-12 px-6 text-base",
};

export type ButtonSize = keyof typeof SIZE;

/**
 * Class string for a button-styled element (links styled as buttons use it too).
 * `rt-control` gives links the same 36px floor (44px on touch) that `<button>` gets, so a
 * link and a button of one size always match; `rt-row-action` (28px) overrides it in rows.
 */
export function buttonClass(
  variant: ButtonVariant = "secondary",
  size: ButtonSize = "md",
  extra = "",
): string {
  return [
    "rt-control inline-flex items-center justify-center gap-2 rounded-sm transition-[background-color,border-color,color] duration-[var(--dur-short)] ease-out disabled:cursor-not-allowed disabled:opacity-50",
    VARIANT[variant],
    SIZE[size],
    extra,
  ]
    .filter(Boolean)
    .join(" ");
}
