import type { ReactNode } from "react";
import type { ApplicantProfile } from "../../api";
import {
  BOOLEAN_FIELDS,
  CHECKBOX_FIELDS,
  CHOICE_FIELDS,
  NUMBER_FIELDS,
  fieldLabel,
} from "../../lib/profileForm";
import type { FieldContext } from "./fieldContext";

/**
 * One application-profile field: the right control for its kind, plus a hint, a
 * "forms ask for this" note when the saved value is blank, and its validation error.
 * The wrapper id `profile-field-<key>` is what "jump to the first problem" scrolls to.
 */
export function ProfileField({
  name,
  ctx,
  hint,
  label,
  auto = false,
}: {
  name: keyof ApplicantProfile;
  ctx: FieldContext;
  hint?: ReactNode;
  label?: string;
  /** A blank value is answered automatically (e.g. from the visa), so it is not a gap. */
  auto?: boolean;
}) {
  const value = ctx.draft[name];
  const id = `pf-${name}`;
  const error = ctx.errors[name];
  const describedBy = error ? `${id}-error` : hint ? `${id}-hint` : undefined;
  const common = {
    id,
    className: `field mt-1 ${error ? "border-danger" : ""}`,
    "aria-invalid": error ? true : undefined,
    "aria-describedby": describedBy,
  };
  let control: ReactNode;
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
  } else if (NUMBER_FIELDS.has(name)) {
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
            {text}
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
        <option value="">Not set</option>
        <option value="true">Yes</option>
        <option value="false">No</option>
      </select>
    );
  } else {
    const password = name === "workday_password";
    const fallback = ctx.defaults[name];
    control = (
      <input
        {...common}
        type={password ? "password" : name === "graduation_date" ? "month" : "text"}
        autoComplete={password ? "new-password" : undefined}
        inputMode={name.endsWith("email") ? "email" : name.endsWith("_url") ? "url" : undefined}
        value={String(value ?? "")}
        placeholder={
          password && ctx.passwordSet
            ? "Saved password · leave blank to keep"
            : fallback
              ? `Default: ${fallback}`
              : name === "graduation_date"
                ? "YYYY-MM"
                : undefined
        }
        onChange={(e) => ctx.set(name, e.target.value)}
      />
    );
  }
  return (
    <div id={`profile-field-${name}`} className="text-sm" onBlur={() => ctx.touch(name)}>
      <label htmlFor={id} className="block">
        {label ?? fieldLabel(name)}
      </label>
      {control}
      {error ? (
        <span id={`${id}-error`} className="mt-1 block text-xs text-danger">
          {error}
        </span>
      ) : (
        hint && (
          <span id={`${id}-hint`} className="mt-1 block text-xs text-ink-muted">
            {hint}
          </span>
        )
      )}
      {!auto && ctx.gapFields.has(name) && (value == null || value === "") && (
        <span className="mt-1 block text-xs text-warn">
          Forms ask for this; blank means autofill skips it.
        </span>
      )}
    </div>
  );
}
