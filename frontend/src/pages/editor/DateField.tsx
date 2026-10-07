import { DateParts } from "../../components/DateParts";

/** A labelled month + year date for the resume editor (stored as `YYYY-MM`). */
export function DateField({
  label,
  value,
  onChange,
  allowPresent = false,
}: {
  label: string;
  value: string;
  onChange: (next: string) => void;
  allowPresent?: boolean;
}) {
  return (
    <div className="block text-sm">
      <span className="mb-1 block text-ink-muted">{label}</span>
      <DateParts label={label} value={value} onChange={onChange} allowPresent={allowPresent} />
    </div>
  );
}
