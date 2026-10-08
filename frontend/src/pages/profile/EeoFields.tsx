import { VETERAN_OPTIONS, type ApplicantProfile, type VeteranStatus } from "../../api";
import { ChoiceOrOther } from "../../components/ChoiceOrOther";
import { Button } from "../../components/ui";
import { fieldLabel } from "../../lib/profileForm";
import { useProfileOptions } from "../../lib/profileOptions";

type Eeo = ApplicantProfile["eeo"];

/**
 * Voluntary self-identification answers. Each is a pick from a fixed list (with Skip and
 * Decline), so autofill can match a form's own wording; "Other…" keeps any free-text
 * answer an older profile held.
 */
export function EeoFields({ eeo, onChange }: { eeo: Eeo; onChange: (next: Eeo) => void }) {
  const options = useProfileOptions();
  const details = options?.race_details[eeo.race] ?? [];
  return (
    <div className="mt-3 grid gap-3 sm:grid-cols-2">
      <div className="text-sm">
        {fieldLabel("gender")}
        <ChoiceOrOther
          id="pf-eeo-gender"
          label="Gender"
          value={eeo.gender ?? ""}
          options={options?.genders ?? ["Male", "Female", "Non-binary"]}
          onChange={(gender) => onChange({ ...eeo, gender })}
        />
      </div>
      <div className="text-sm">
        {fieldLabel("race")}
        <ChoiceOrOther
          id="pf-eeo-race"
          label="Race"
          value={eeo.race ?? ""}
          options={options?.races ?? []}
          onChange={(race) =>
            onChange({
              ...eeo,
              race,
              // A detail from the previous race ("Chinese" under Asian) no longer applies.
              race_detail: (options?.race_details[race] ?? []).includes(eeo.race_detail ?? "")
                ? eeo.race_detail
                : "",
            })
          }
        />
      </div>
      <div className="text-sm">
        {fieldLabel("race_detail")}
        <ChoiceOrOther
          // Remount when the race changes so "Other…" does not outlive the list it belonged to.
          key={eeo.race}
          id="pf-eeo-race_detail"
          label="Race detail"
          value={eeo.race_detail ?? ""}
          options={details}
          onChange={(race_detail) => onChange({ ...eeo, race_detail })}
        />
      </div>
      <div className="text-sm">
        {fieldLabel("disability")}
        <ChoiceOrOther
          id="pf-eeo-disability"
          label="Disability"
          value={eeo.disability ?? ""}
          options={options?.disability ?? ["Yes", "No"]}
          onChange={(disability) => onChange({ ...eeo, disability })}
        />
      </div>
      <div className="text-sm">
        <label className="block">
          {fieldLabel("veteran")}
          <select
            className="field mt-1"
            value={eeo.veteran ?? ""}
            onChange={(e) =>
              onChange({ ...eeo, veteran: e.target.value as VeteranStatus, veteran_legacy: "" })
            }
          >
            {VETERAN_OPTIONS.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </label>
        {eeo.veteran_legacy && (
          <span className="mt-1 flex flex-wrap items-center gap-2 text-xs text-attn">
            Converted from your earlier answer “{eeo.veteran_legacy}”. Forms tell apart “not a
            veteran” and “not a protected veteran”, so please check it.
            <Button size="sm" onClick={() => onChange({ ...eeo, veteran_legacy: "" })}>
              Looks right
            </Button>
          </span>
        )}
      </div>
      <label className="text-sm">
        Hispanic or Latino
        <select
          className="field mt-1"
          value={eeo.hispanic_latino == null ? "" : String(eeo.hispanic_latino)}
          onChange={(e) =>
            onChange({
              ...eeo,
              hispanic_latino: e.target.value === "" ? null : e.target.value === "true",
            })
          }
        >
          <option value="">Not set</option>
          <option value="true">Yes</option>
          <option value="false">No</option>
        </select>
      </label>
    </div>
  );
}
