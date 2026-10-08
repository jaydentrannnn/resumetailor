import { ChoiceOrOther } from "../../components/ChoiceOrOther";
import { useProfileOptions } from "../../lib/profileOptions";
import type { FieldContext } from "./fieldContext";
import { FieldFrame } from "./FieldFrame";

export function EducationField({ ctx }: { ctx: FieldContext }) {
  const options = useProfileOptions();
  const name = "highest_education_obtained";
  const value = ctx.draft[name] ?? "";
  const normalized = value
    .normalize("NFKD")
    .toLowerCase()
    .replace(/[^\p{L}\p{N}_]+/gu, " ")
    .trim();
  // Display legacy spellings as a listed choice without changing the saved draft.
  const displayed = options?.education_level_aliases?.[normalized] ?? value;
  return (
    <FieldFrame
      name={name}
      ctx={ctx}
      blank={!value.trim()}
      htmlFor="pf-highest_education_obtained"
      hint="Choose education you have already completed. Degrees still in progress come from your resume."
    >
      <ChoiceOrOther
        id="pf-highest_education_obtained"
        label="Highest education completed"
        value={displayed}
        options={options?.education_levels ?? []}
        allowDecline={false}
        blankLabel="Not set — leave completed-education questions unanswered"
        onChange={(next) => ctx.set(name, next)}
      />
    </FieldFrame>
  );
}
