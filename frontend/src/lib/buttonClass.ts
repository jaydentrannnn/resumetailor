export type ButtonVariant = "primary" | "secondary" | "danger" | "ghost";

// Green is never a button fill: primary is ink (black in light, white in dark).
const VARIANT: Record<ButtonVariant, string> = {
  primary: "bg-primary font-medium text-on-primary hover:bg-primary/85",
  secondary: "border border-line-hover bg-field font-medium text-ink hover:border-ink",
  danger: "border border-danger/45 bg-field font-medium text-danger hover:border-danger",
  ghost: "font-medium text-ink-muted hover:bg-sunken hover:text-ink",
};

const SIZE = { sm: "px-3 py-1.5 text-xs", md: "px-4 py-2 text-[13px]", lg: "px-4 py-3 text-sm" };

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
