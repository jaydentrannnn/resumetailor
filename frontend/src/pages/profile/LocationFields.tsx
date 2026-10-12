import type { ReactNode } from "react";
import type { ApplicantProfile } from "../../api";
import { useProfileOptions } from "../../lib/profileOptions";
import type { FieldContext } from "./fieldContext";
import { FieldFrame } from "./FieldFrame";

/**
 * Country and state as pickers. The state list follows the chosen country (US states,
 * Canadian provinces); a country without a list keeps a text box. A saved value outside
 * the list (an abbreviation, an older spelling) stays selectable instead of vanishing.
 */
export function LocationField(props: {
  name: keyof ApplicantProfile;
  ctx: FieldContext;
  label?: string;
  hint?: ReactNode;
  auto?: boolean;
}) {
  const { name, ctx } = props;
  const options = useProfileOptions();
  const id = `pf-${name}`;
  const value = String(ctx.draft[name] ?? "");
  const error = ctx.errors[name];
  const common = { id, "aria-invalid": error ? true : undefined };
  if (name === "state") {
    const states = options?.subdivisions[ctx.draft.country] ?? [];
    const named = states.find(
      (state) => state.name === value || state.code.toLowerCase() === value.toLowerCase(),
    );
    const label = ctx.draft.country === "Canada" ? "Province" : "State or province";
    return (
      <FieldFrame {...props} label={props.label ?? label} blank={!value}>
        {states.length === 0 ? (
          <input
            {...common}
            className="field mt-1"
            value={value}
            onChange={(e) => ctx.set("state", e.target.value)}
          />
        ) : (
          <select
            {...common}
            className="field mt-1"
            value={named?.name ?? value}
            onChange={(e) => ctx.set("state", e.target.value)}
          >
            <option value="">Not set</option>
            {!named && value && <option value={value}>{value}</option>}
            {states.map((state) => (
              <option key={state.code} value={state.name}>
                {state.name}
              </option>
            ))}
          </select>
        )}
      </FieldFrame>
    );
  }
  const countries = options?.countries ?? [];
  const known = countries.find(
    (country) => country.name === value || country.aliases.includes(value),
  );
  return (
    <FieldFrame {...props} blank={!value}>
      <select
        {...common}
        className="field mt-1"
        value={known?.name ?? value}
        onChange={(e) => {
          const next = e.target.value;
          if (name !== "country") return ctx.set(name, next);
          // A state from the old country's list means nothing in the new one.
          const keepState = !!options?.subdivisions[next]?.some(
            (state) => state.name === ctx.draft.state,
          );
          ctx.setMany(keepState ? { country: next } : { country: next, state: "" });
        }}
      >
        <option value="">Not set</option>
        {!known && value && <option value={value}>{value}</option>}
        {countries.map((country) => (
          <option key={country.code} value={country.name}>
            {country.name}
          </option>
        ))}
      </select>
    </FieldFrame>
  );
}

/**
 * Countries the applicant may work in without sponsorship, as removable chips plus an
 * "Add country" picker. Saves `authorization_countries`; the older single
 * `authorization_country` mirrors the first entry.
 */
export function AuthorizationCountriesField(props: {
  name: keyof ApplicantProfile;
  ctx: FieldContext;
  label?: string;
  hint?: ReactNode;
  auto?: boolean;
}) {
  const { ctx } = props;
  const options = useProfileOptions();
  const id = `pf-${props.name}`;
  const saved = ctx.draft.authorization_countries ?? [];
  const chosen = saved.length
    ? saved
    : ctx.draft.authorization_country
      ? [ctx.draft.authorization_country]
      : [];
  const save = (next: string[]) =>
    ctx.setMany({ authorization_countries: next, authorization_country: next[0] ?? "" });
  const remaining = (options?.countries ?? []).filter((country) => !chosen.includes(country.name));
  return (
    <FieldFrame {...props} blank={chosen.length === 0}>
      {chosen.length > 0 && (
        <ul className="mt-1 flex flex-wrap gap-1" aria-label="Authorized countries">
          {chosen.map((country) => (
            <li
              key={country}
              className="flex items-center gap-1 rounded border border-line px-2 py-0.5 text-xs"
            >
              {country}
              <button
                type="button"
                className="text-ink-muted hover:text-ink"
                aria-label={`Remove ${country}`}
                onClick={() => save(chosen.filter((c) => c !== country))}
              >
                ×
              </button>
            </li>
          ))}
        </ul>
      )}
      <select
        id={id}
        className="field mt-1"
        value=""
        onChange={(e) => e.target.value && save([...chosen, e.target.value])}
      >
        <option value="">{chosen.length ? "Add another country" : "Add a country"}</option>
        {remaining.map((country) => (
          <option key={country.code} value={country.name}>
            {country.name}
          </option>
        ))}
      </select>
    </FieldFrame>
  );
}
