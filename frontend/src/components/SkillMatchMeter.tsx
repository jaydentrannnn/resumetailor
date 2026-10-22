import { Meter } from "./ui";

/**
 * Matched required skills as a number out of 100 with a mini meter; the raw count is the
 * tooltip. Shared by the Apply table and the Tailor page's recent runs so both read alike.
 */
export function SkillMatchMeter({
  matched,
  total,
  label,
  where = "in your resume",
}: {
  matched: number;
  total: number;
  /** Accessible name for the meter ("Skill match for Acme"). */
  label: string;
  /** What `matched` counts: the master resume (Apply) or a tailored page (runs). */
  where?: string;
}) {
  const pct = Math.round((matched / total) * 100);
  return (
    <span
      className="inline-flex items-center gap-2"
      title={`${matched} of ${total} required skills ${where}`}
    >
      <span className="font-mono text-[13px] tabular-nums text-ink">{pct}</span>
      <Meter
        className="w-11"
        tone="ink"
        value={pct}
        label={label}
        valueText={`${matched} of ${total} required skills ${where}`}
      />
    </span>
  );
}
