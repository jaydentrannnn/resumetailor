import type { ReactNode } from "react";
import type { ApplicantProfile } from "../../api";
import { fieldLabel } from "../../lib/profileForm";
import type { FieldContext } from "./fieldContext";

/**
 * The label, error line, hint and "forms ask for this" note shared by every profile
 * field. The wrapper id `profile-field-<key>` is what "jump to the first problem"
 * scrolls to; `htmlFor` names the control the label points at.
 */
export function FieldFrame({
  name,
  ctx,
  label,
  hint,
  auto = false,
  htmlFor,
  blank,
  children,
}: {
  name: keyof ApplicantProfile;
  ctx: FieldContext;
  label?: string;
  hint?: ReactNode;
  /** A blank value is answered automatically (e.g. from the visa), so it is not a gap. */
  auto?: boolean;
  htmlFor?: string;
  /** Whether the saved value is blank, which is when a gap warning applies. */
  blank: boolean;
  children: ReactNode;
}) {
  const id = `pf-${name}`;
  const error = ctx.errors[name];
  return (
    <div id={`profile-field-${name}`} className="text-sm" onBlur={() => ctx.touch(name)}>
      <label htmlFor={htmlFor ?? id} className="block">
        {label ?? fieldLabel(name)}
      </label>
      {children}
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
      {!auto && ctx.gapFields.has(name) && blank && (
        <span className="mt-1 block text-xs text-attn">
          Forms ask for this; blank means autofill skips it.
        </span>
      )}
    </div>
  );
}
