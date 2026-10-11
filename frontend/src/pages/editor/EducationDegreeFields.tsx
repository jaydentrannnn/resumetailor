import { useId } from "react";
import { ChipListField } from "../../components/ChipListField";
import { ChoiceOrOther } from "../../components/ChoiceOrOther";
import { Button, Segmented, Switch } from "../../components/ui";
import { generatedDegree, withDegreeParts, withDetectedParts } from "../../lib/degreeLine";
import { useProfileOptions } from "../../lib/profileOptions";
import type { DegreeFormat, Education } from "../../lib/resumeEdit";
import { TextField } from "./TextField";

const FORMATS: { id: DegreeFormat; label: string }[] = [
  { id: "semicolon", label: "; Minor in" },
  { id: "comma", label: ", Minor in" },
  { id: "pipe", label: "| Minor in" },
];

/**
 * Degree type, majors and minors (also used for application forms), and the printed
 * degree line — generated from those parts, or written by hand. Majors split on ";" so a
 * field of study containing a comma stays one chip.
 */
export function EducationDegreeFields({
  edu,
  onChange,
}: {
  edu: Education;
  onChange: (next: Education) => void;
}) {
  const id = useId();
  const options = useProfileOptions();
  const generated = edu.degree_mode === "generated";
  const set = (patch: Partial<Education>) => onChange(withDegreeParts(edu, patch));
  const hasParts = !!(edu.degree_type || edu.majors?.length || edu.minors?.length);
  return (
    <div className="space-y-3 sm:col-span-2">
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
        <label className="block text-sm" htmlFor={`${id}-type`}>
          <span className="mb-1 block text-ink-muted">Degree type</span>
          <ChoiceOrOther
            id={`${id}-type`}
            label="Degree type"
            value={edu.degree_type ?? ""}
            onChange={(degree_type) => set({ degree_type })}
            options={options?.degree_types ?? []}
            blankLabel="Choose…"
            allowDecline={false}
          />
        </label>
        <ChipListField
          label="Majors"
          items={edu.majors ?? []}
          onChange={(majors) => set({ majors })}
          suggestions={options?.fields_of_study}
          separators={/;/}
          placeholder="Add a major"
        />
        <ChipListField
          label="Minors"
          items={edu.minors ?? []}
          onChange={(minors) => set({ minors })}
          suggestions={options?.fields_of_study}
          separators={/;/}
          placeholder="Add a minor"
        />
      </div>
      <div className="rounded-sm border border-line px-3 py-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <span className="text-xs font-medium text-ink-2">Printed on your resume</span>
          <label className="flex items-center gap-2 text-xs text-ink-muted">
            Write it myself
            <Switch
              checked={!generated}
              onChange={(manual) =>
                onChange(
                  manual
                    ? { ...edu, degree_mode: "manual" }
                    : { ...edu, degree_mode: "generated", degree: generatedDegree(edu) },
                )
              }
            />
          </label>
        </div>
        {generated ? (
          <>
            <p className="mt-2 text-sm text-ink">
              {edu.degree || <span className="text-ink-muted">Add a degree type or major</span>}
            </p>
            {(edu.minors?.length ?? 0) > 0 && (edu.majors?.length || edu.degree_type) && (
              <Segmented
                className="mt-2"
                label="How the minor is joined"
                items={FORMATS}
                value={edu.degree_format ?? "semicolon"}
                onChange={(fmt) => set({ degree_format: fmt as DegreeFormat })}
              />
            )}
          </>
        ) : (
          <div className="mt-2">
            <TextField label="Degree" value={edu.degree} onChange={(degree) => set({ degree })} />
            {!hasParts && edu.degree.trim() && (
              <Button
                variant="plain"
                className="mt-2"
                onClick={() => onChange(withDetectedParts(edu))}
              >
                Fill type, majors and minors from this line
              </Button>
            )}
          </div>
        )}
        <p className="mt-2 text-xs text-ink-muted">
          Majors and minors also answer application forms; the first major fills a single “Major”
          field.
        </p>
      </div>
    </div>
  );
}
