import logoMarkBlack from "../assets/logo-mark-black.svg";

/** The same mark everywhere, painted with the current theme's ink. */
export function LogoMark({ className = "h-5 w-4" }: { className?: string }) {
  return (
    <span
      aria-hidden="true"
      className={`inline-block shrink-0 bg-ink ${className}`}
      style={{ mask: `url("${logoMarkBlack}") center / contain no-repeat` }}
    />
  );
}
