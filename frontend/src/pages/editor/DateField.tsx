import { DateParts } from "../../components/DateParts";
import { BufferedField } from "./BufferedField";

/** A labelled month + year date for the resume editor (stored as `YYYY-MM`). */
export function DateField({
  label,
  value,
  onChange,
  allowPresent = false,
  optionalDay = false,
}: {
  label: string;
  value: string;
  onChange: (next: string) => void;
  allowPresent?: boolean;
  optionalDay?: boolean;
}) {
  return (
    <div className="block text-sm">
      <span className="mb-1 block text-ink-muted">{label}</span>
      <BufferedField value={value} onChange={onChange}>
        {(draft, setDraft) => (
          <DateParts
            label={label}
            value={draft}
            onChange={setDraft}
            allowPresent={allowPresent}
            precision={optionalDay ? "optional_day" : "month"}
          />
        )}
      </BufferedField>
    </div>
  );
}
