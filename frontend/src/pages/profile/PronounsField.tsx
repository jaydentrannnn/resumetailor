import type { ReactNode } from "react";
import type { ApplicantProfile } from "../../api";
import { ChoiceOrOther } from "../../components/ChoiceOrOther";
import { useProfileOptions } from "../../lib/profileOptions";
import type { FieldContext } from "./fieldContext";
import { FieldFrame } from "./FieldFrame";

/** Pronouns: a short list plus Other, never a bare text box. */
export function PronounsField(props: {
  name: keyof ApplicantProfile;
  ctx: FieldContext;
  label?: string;
  hint?: ReactNode;
  auto?: boolean;
}) {
  const options = useProfileOptions();
  const value = String(props.ctx.draft.pronouns ?? "");
  return (
    <FieldFrame {...props} blank={!value} htmlFor="pf-pronouns">
      <ChoiceOrOther
        id="pf-pronouns"
        label="Pronouns"
        value={value}
        options={options?.pronouns ?? ["He/him", "She/her", "They/them"]}
        allowDecline={false}
        blankLabel="Skip this question"
        onChange={(next) => props.ctx.set("pronouns", next)}
      />
    </FieldFrame>
  );
}
