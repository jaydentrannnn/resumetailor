import type { ReactNode } from "react";
import type { ApplicantProfile } from "../../api";
import { phoneLabel, useProfileOptions } from "../../lib/profileOptions";
import type { FieldContext } from "./fieldContext";
import { FieldFrame } from "./FieldFrame";

/**
 * Phone country as forms show it ("United States (+1)"). One pick sets both the dial
 * code and the region that tells countries sharing a code apart.
 */
export function PhoneCountryField(props: {
  name: keyof ApplicantProfile;
  ctx: FieldContext;
  label?: string;
  hint?: ReactNode;
  auto?: boolean;
}) {
  const { ctx } = props;
  const options = useProfileOptions();
  const code = ctx.draft.phone_country_code || "+1";
  const region = ctx.draft.phone_country_region || "";
  const countries = options?.countries ?? [];
  const current =
    countries.find((country) => country.name === region) ??
    countries.find((country) => country.aliases.includes(region)) ??
    countries.find((country) => country.dial === code);
  return (
    <FieldFrame
      {...props}
      label="Phone country"
      blank={false}
      htmlFor="pf-phone_country_code"
      hint={props.hint}
    >
      <select
        id="pf-phone_country_code"
        className="field mt-1"
        value={current?.name ?? ""}
        disabled={!options}
        onChange={(e) => {
          const picked = countries.find((country) => country.name === e.target.value);
          if (!picked) return;
          ctx.setMany({ phone_country_region: picked.name, phone_country_code: picked.dial });
        }}
      >
        {!current && <option value="">{options ? `${code} (choose a country)` : code}</option>}
        {countries.map((country) => (
          <option key={country.code} value={country.name}>
            {phoneLabel(country)}
          </option>
        ))}
      </select>
    </FieldFrame>
  );
}
