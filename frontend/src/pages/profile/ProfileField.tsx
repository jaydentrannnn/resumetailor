import type { ReactNode } from "react";
import type { ApplicantProfile } from "../../api";
import { DateParts } from "../../components/DateParts";
import {
  BOOLEAN_FIELDS,
  CHECKBOX_FIELDS,
  CHOICE_FIELDS,
  DATE_FIELDS,
  NUMBER_FIELDS,
  fieldLabel,
} from "../../lib/profileForm";
import type { FieldContext } from "./fieldContext";
import { FieldFrame } from "./FieldFrame";
import { EducationField } from "./EducationField";
import { LocationField } from "./LocationFields";
import { NoticePeriodField } from "./NoticePeriodField";
import { PhoneCountryField } from "./PhoneCountryField";
import { PronounsField } from "./PronounsField";

/**
 * One application-profile field: the right control for its kind, plus a hint, a
 * "forms ask for this" note when the saved value is blank, and its validation error.
 * What a blank value stands for (the resume's value, a default, "Auto from visa") is
 * shown inside the control, never as a line below it.
 */
export function ProfileField({
  name,
  ctx,
  hint,
  label,
  auto = false,
  blankLabel,
}: {
  name: keyof ApplicantProfile;
  ctx: FieldContext;
  hint?: ReactNode;
  label?: string;
  auto?: boolean;
  /** Text of a select's empty option when something answers it ("Auto from visa: Yes"). */
  blankLabel?: string;
}) {
  const value = ctx.draft[name];
  const id = `pf-${name}`;
  const error = ctx.errors[name];
  const describedBy = error ? `${id}-error` : hint ? `${id}-hint` : undefined;
  const frame = { name, ctx, label, hint, auto };
  const common = {
    id,
    className: `field mt-1 ${error ? "border-danger" : ""}`,
    "aria-invalid": error ? true : undefined,
    "aria-describedby": describedBy,
  };
  const blank = value == null || value === "";
  if (CHECKBOX_FIELDS.has(name)) {
    return (
      <div id={`profile-field-${name}`} className="text-sm sm:col-span-2">
        <label className="flex items-center gap-2">
          <input
            id={id}
            type="checkbox"
            checked={value === true}
            onChange={(e) => ctx.set(name, e.target.checked)}
          />
          {label ?? fieldLabel(name)}
        </label>
        {hint && (
          <span id={`${id}-hint`} className="mt-1 block text-xs text-ink-muted">
            {hint}
          </span>
        )}
      </div>
    );
  }
  if (name === "notice_period") return <NoticePeriodField {...frame} />;
  if (name === "phone_country_code") return <PhoneCountryField {...frame} />;
  if (name === "pronouns") return <PronounsField {...frame} />;
  if (name === "highest_education_obtained") return <EducationField ctx={ctx} />;
  if (name === "country" || name === "state" || name === "authorization_country")
    return <LocationField {...frame} />;
  const precision = DATE_FIELDS[name];
  if (precision) {
    return (
      <FieldFrame {...frame} blank={blank} htmlFor={`${id}-month`}>
        <DateParts
          id={`${id}-month`}
          label={label ?? fieldLabel(name)}
          precision={precision}
          value={String(value ?? "")}
          fallback={ctx.fallbacks[name]}
          invalid={!!error}
          onChange={(next) => ctx.set(name, next)}
        />
      </FieldFrame>
    );
  }
  let control: ReactNode;
  if (NUMBER_FIELDS.has(name)) {
    const whole = name === "hours_per_week_available";
    control = (
      <input
        {...common}
        type="number"
        min={0}
        max={whole ? 80 : undefined}
        step={whole ? 1 : "any"}
        inputMode={whole ? "numeric" : "decimal"}
        value={value == null ? "" : String(value)}
        onChange={(e) => ctx.set(name, e.target.value === "" ? null : Number(e.target.value))}
      />
    );
  } else if (CHOICE_FIELDS[name]) {
    control = (
      <select
        {...common}
        value={String(value ?? "")}
        onChange={(e) => ctx.set(name, e.target.value)}
      >
        {CHOICE_FIELDS[name].map(([option, text]) => (
          <option key={option} value={option}>
            {option === "" && blankLabel ? blankLabel : text}
          </option>
        ))}
      </select>
    );
  } else if (BOOLEAN_FIELDS.has(name)) {
    control = (
      <select
        {...common}
        value={value == null ? "" : String(value)}
        onChange={(e) => ctx.set(name, e.target.value === "" ? null : e.target.value === "true")}
      >
        <option value="">{blankLabel ?? "Not set"}</option>
        <option value="true">Yes</option>
        <option value="false">No</option>
      </select>
    );
  } else {
    const password = name === "workday_password";
    const fromResume = ctx.fallbacks[name];
    const fallback = ctx.defaults[name];
    control = (
      <input
        {...common}
        type={password ? "password" : "text"}
        autoComplete={password ? "new-password" : undefined}
        inputMode={
          name === "high_school_graduation_year"
            ? "numeric"
            : name.endsWith("email")
              ? "email"
              : name.endsWith("_url")
                ? "url"
                : undefined
        }
        maxLength={name === "high_school_graduation_year" ? 4 : undefined}
        value={String(value ?? "")}
        placeholder={
          password && ctx.passwordSet
            ? "Saved password · leave blank to keep"
            : fromResume
              ? name === "high_school_graduation_year"
                ? `Auto from college start: ${fromResume}`
                : `From resume: ${fromResume}`
              : fallback
                ? `Default: ${fallback}`
                : undefined
        }
        onChange={(e) => ctx.set(name, e.target.value)}
      />
    );
  }
  return (
    <FieldFrame {...frame} blank={blank}>
      {control}
    </FieldFrame>
  );
}
