/**
 * The on/off look: a square track with a sliding knob, green (`selected`) when on.
 * Use it for a setting that takes effect at once (a source, the nightly run, a Tailor
 * option); keep a checkbox for picking items out of a list.
 */
export function SwitchTrack({ on }: { on: boolean }) {
  return (
    <span
      aria-hidden="true"
      className={`inline-flex h-5 w-9 shrink-0 items-center rounded-sm border transition-colors duration-[var(--dur-short)] ${on ? "border-selected-line bg-selected" : "border-line-hover bg-sunken"}`}
    >
      <span
        className={`inline-block size-3.5 rounded-xs transition-transform duration-[var(--dur-short)] ${on ? "translate-x-[17px] bg-on-selected" : "translate-x-0.5 bg-ink-muted"}`}
      />
    </span>
  );
}

/**
 * A native checkbox with `role="switch"` under the track, so it keeps the label click,
 * Space key and form semantics. Put it inside a `<label>` or pass `label`.
 */
export function Switch({
  checked,
  onChange,
  disabled,
  label,
  className = "",
}: {
  checked: boolean;
  onChange: (on: boolean) => void;
  disabled?: boolean;
  /** Accessible name when the switch has no surrounding `<label>`. */
  label?: string;
  className?: string;
}) {
  return (
    <span
      className={`relative inline-flex shrink-0 rounded-sm has-[:focus-visible]:outline-2 has-[:focus-visible]:outline-offset-2 has-[:focus-visible]:outline-accent has-[:disabled]:opacity-50 ${className}`.trim()}
    >
      <input
        type="checkbox"
        role="switch"
        aria-label={label}
        checked={checked}
        disabled={disabled}
        onChange={(e) => onChange(e.target.checked)}
        className="absolute inset-0 m-0 cursor-pointer opacity-0 disabled:cursor-not-allowed"
      />
      <SwitchTrack on={checked} />
    </span>
  );
}
