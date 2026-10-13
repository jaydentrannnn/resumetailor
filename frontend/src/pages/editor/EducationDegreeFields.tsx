import { Button, Switch, buttonClass } from "../../components/ui";
import {
  generatedDegree,
  majorEntries,
  withDegreeParts,
  withDetectedParts,
} from "../../lib/degreeLine";
import type { DegreeFormat, Education } from "../../lib/resumeEdit";
import { EducationStudies } from "./EducationStudies";
import { TextField } from "./TextField";

const FORMATS: { id: DegreeFormat; label: string; name: string }[] = [
  { id: "semicolon", label: ";", name: "Semicolon" },
  { id: "comma", label: ",", name: "Comma" },
  { id: "pipe", label: "|", name: "Vertical bar" },
];

export function EducationDegreeFields({
  edu,
  onChange,
}: {
  edu: Education;
  onChange: (next: Education) => void;
}) {
  const generated = edu.degree_mode === "generated";
  const set = (patch: Partial<Education>) => onChange(withDegreeParts(edu, patch));
  const hasParts = !!(edu.degree_type || majorEntries(edu).length || edu.minors?.length);
  return (
    <div className="space-y-4 sm:col-span-2">
      <EducationStudies edu={edu} onChange={set} />
      <div className="border-t border-line pt-3">
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
          <div className="mt-2 flex flex-wrap items-center justify-between gap-3">
            <p className="min-w-0 flex-1 text-base font-semibold text-ink break-words">
              {edu.degree || (
                <span className="font-normal text-ink-muted">Add a major or minor</span>
              )}
            </p>
            <span className="flex shrink-0 gap-1" role="group" aria-label="Degree separator">
              {FORMATS.map((fmt) => (
                <button
                  key={fmt.id}
                  type="button"
                  aria-label={fmt.name}
                  title={fmt.name}
                  aria-pressed={(edu.degree_format ?? "semicolon") === fmt.id}
                  className={`${buttonClass((edu.degree_format ?? "semicolon") === fmt.id ? "primary" : "plain", "sm")} w-8`}
                  onClick={() => set({ degree_format: fmt.id })}
                >
                  {fmt.label}
                </button>
              ))}
            </span>
          </div>
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
          Majors sharing a degree are joined together. The first major answers a single Major field
          on applications.
        </p>
      </div>
    </div>
  );
}
