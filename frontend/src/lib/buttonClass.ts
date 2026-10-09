export type ButtonVariant =
  | "primary"
  | "secondary"
  | "outline"
  | "attention"
  | "success"
  | "danger"
  | "ghost";

// Green is never a button fill. Primary and secondary are both ink (black in light, white
// in dark): a field-coloured secondary vanished into its tile in both themes. `outline` is
// the quiet one (pagination, Save beside an input, Copy): an ink outline and ink text on
// the page colour (white in light, near-black in dark), a step off the tile. `attention`
// and `success` are the same outline in orange and green, for row actions whose colour
// says what they are (needs you / ready to fill), beside `danger` (failed, retry).
const INK = "bg-primary font-medium text-on-primary hover:bg-primary/85";
export const OUTLINE =
  "border border-ink/55 bg-field font-medium text-ink hover:border-ink hover:bg-sunken";
const VARIANT: Record<ButtonVariant, string> = {
  primary: INK,
  secondary: INK,
  outline: OUTLINE,
  attention: "border border-attn/55 bg-field font-medium text-attn hover:border-attn",
  success: "border border-accent/55 bg-field font-medium text-accent hover:border-accent",
  danger: "border border-danger/45 bg-field font-medium text-danger hover:border-danger",
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
