export type ButtonVariant = "primary" | "secondary" | "danger" | "ghost";

const VARIANT: Record<ButtonVariant, string> = {
  primary: "bg-accent font-semibold text-on-accent hover:brightness-110",
  secondary:
    "border border-line bg-panel font-medium text-ink hover:border-accent hover:text-accent",
  danger: "border border-danger/40 bg-danger-soft font-medium text-danger hover:border-danger",
  ghost: "font-medium text-ink-muted hover:bg-paper hover:text-ink",
};

const SIZE = { sm: "px-3 py-1.5 text-sm", md: "px-4 py-2 text-sm", lg: "px-4 py-3 text-sm" };

export type ButtonSize = keyof typeof SIZE;

/** Class string for a button-styled element (links styled as buttons use it too). */
export function buttonClass(
  variant: ButtonVariant = "secondary",
  size: ButtonSize = "md",
  extra = "",
): string {
  return [
    "inline-flex items-center justify-center gap-2 rounded-lg transition-[filter,color,border-color] duration-[var(--dur-short)] ease-out disabled:cursor-not-allowed disabled:opacity-50",
    VARIANT[variant],
    SIZE[size],
    extra,
  ]
    .filter(Boolean)
    .join(" ");
}
