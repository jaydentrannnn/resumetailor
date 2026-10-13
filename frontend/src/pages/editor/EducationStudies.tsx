import { useId, useState } from "react";
import { ChoiceOrOther } from "../../components/ChoiceOrOther";
import { Button } from "../../components/ui";
import { majorEntries } from "../../lib/degreeLine";
import { useProfileOptions } from "../../lib/profileOptions";
import type { Education } from "../../lib/resumeEdit";

type Study = { kind: "major" | "minor"; name: string; degree_type: string };

export function EducationStudies({
  edu,
  onChange,
}: {
  edu: Education;
  onChange: (patch: Partial<Education>) => void;
}) {
  const id = useId();
  const options = useProfileOptions();
  const [adding, setAdding] = useState(false);
  const rows: Study[] = [
    ...majorEntries(edu).map((entry) => ({ ...entry, kind: "major" as const })),
    ...(edu.minors ?? []).map((name) => ({ name, kind: "minor" as const, degree_type: "" })),
  ];
  function save(next: Study[]) {
    onChange({
      major_entries: next
        .filter((row) => row.kind === "major")
        .map(({ name, degree_type }) => ({ name, degree_type })),
      minors: next.filter((row) => row.kind === "minor").map((row) => row.name),
    });
  }
  function update(index: number, patch: Partial<Study>) {
    save(rows.map((row, i) => (i === index ? { ...row, ...patch } : row)));
  }
  function move(index: number, delta: number) {
    const next = [...rows];
    [next[index], next[index + delta]] = [next[index + delta], next[index]];
    save(next);
  }
  return (
    <div className="space-y-3">
      {rows.map((row, index) => (
        <div key={`${row.kind}-${index}`} className="border-b border-line pb-3">
          <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
            <span className="text-sm font-medium text-ink">
              {row.kind === "major" ? "Major" : "Minor"} {index + 1}
            </span>
            <span className="flex gap-1">
              <Button
                variant="plain"
                size="sm"
                disabled={index === 0 || rows[index - 1].kind !== row.kind}
                aria-label={`Move ${row.kind} ${index + 1} up`}
                onClick={() => move(index, -1)}
              >
                ↑
              </Button>
              <Button
                variant="plain"
                size="sm"
                disabled={index === rows.length - 1 || rows[index + 1].kind !== row.kind}
                aria-label={`Move ${row.kind} ${index + 1} down`}
                onClick={() => move(index, 1)}
              >
                ↓
              </Button>
              <Button
                variant="plain"
                size="sm"
                aria-label={`Remove ${row.kind} ${index + 1}`}
                onClick={() => save(rows.filter((_, i) => i !== index))}
              >
                Remove
              </Button>
            </span>
          </div>
          <div className="grid gap-3 sm:grid-cols-3">
            <label className="text-sm">
              <span className="block text-ink-muted">Entry type</span>
              <select
                className="field mt-1"
                aria-label={`Entry ${index + 1} type`}
                value={row.kind}
                onChange={(e) =>
                  update(index, {
                    kind: e.target.value as Study["kind"],
                    degree_type: row.degree_type || edu.degree_type || "",
                  })
                }
              >
                <option value="major">Major</option>
                <option value="minor">Minor</option>
              </select>
            </label>
            <label className="text-sm">
              <span className="block text-ink-muted">Field of study</span>
              <input
                className="field mt-1"
                aria-label={`${row.kind === "major" ? "Major" : "Minor"} ${index + 1} field of study`}
                list={`${id}-fields`}
                value={row.name}
                onChange={(e) => update(index, { name: e.target.value })}
              />
            </label>
            {row.kind === "major" && (
              <label className="text-sm">
                <span className="block text-ink-muted">Degree type</span>
                <ChoiceOrOther
                  id={`${id}-degree-${index}`}
                  label={`Major ${index + 1} degree type`}
                  value={row.degree_type}
                  onChange={(degree_type) => update(index, { degree_type })}
                  options={options?.degree_types ?? []}
                  blankLabel="Choose…"
                  allowDecline={false}
                />
              </label>
            )}
          </div>
        </div>
      ))}
      <datalist id={`${id}-fields`}>
        {options?.fields_of_study.map((name) => (
          <option key={name} value={name} />
        ))}
      </datalist>
      {adding ? (
        <div className="flex flex-wrap gap-2">
          <Button
            variant="plain"
            onClick={() => {
              save([...rows, { kind: "major", name: "", degree_type: edu.degree_type ?? "" }]);
              setAdding(false);
            }}
          >
            Major
          </Button>
          <Button
            variant="plain"
            onClick={() => {
              save([...rows, { kind: "minor", name: "", degree_type: "" }]);
              setAdding(false);
            }}
          >
            Minor
          </Button>
          <Button variant="plain" onClick={() => setAdding(false)}>
            Cancel
          </Button>
        </div>
      ) : (
        <Button variant="plain" onClick={() => setAdding(true)}>
          Add entry
        </Button>
      )}
    </div>
  );
}
