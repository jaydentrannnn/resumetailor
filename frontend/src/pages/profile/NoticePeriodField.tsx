import type { ReactNode } from "react";
import type { ApplicantProfile, NoticeUnit } from "../../api";
import { noticeLabel } from "../../lib/profileForm";
import type { FieldContext } from "./fieldContext";
import { FieldFrame } from "./FieldFrame";

const UNITS: [NoticeUnit, string][] = [
  ["day", "Days"],
  ["week", "Weeks"],
  ["month", "Months"],
];

/**
 * Notice period as a number and a unit. Forms ask in other units ("in days", "Less than
 * 1 month"), so autofill converts the number into whatever the form wants.
 */
export function NoticePeriodField(props: {
  name: keyof ApplicantProfile;
  ctx: FieldContext;
  label?: string;
  hint?: ReactNode;
  auto?: boolean;
}) {
  const { ctx } = props;
  const value = ctx.draft.notice_period_value;
  const unit = ctx.draft.notice_period_unit ?? "week";
  const legacy = value == null && !!ctx.draft.notice_period;
  function update(nextValue: number | null, nextUnit: NoticeUnit) {
    ctx.setMany({
      notice_period_value: nextValue,
      notice_period_unit: nextUnit,
      notice_period: noticeLabel(nextValue, nextUnit),
    });
  }
  return (
    <FieldFrame
      {...props}
      blank={value == null && !ctx.draft.notice_period}
      htmlFor="pf-notice_period_value"
      hint={props.hint ?? (legacy ? `Saved as “${ctx.draft.notice_period}”.` : undefined)}
    >
      <div className="mt-1 flex gap-2">
        <input
          id="pf-notice_period_value"
          className="field w-24"
          type="number"
          min={0}
          max={999}
          step={1}
          inputMode="numeric"
          aria-label="Notice period amount"
          placeholder={legacy ? "—" : "0"}
          value={value == null ? "" : String(value)}
          onChange={(e) =>
            update(
              e.target.value === "" ? null : Math.max(0, Math.trunc(Number(e.target.value))),
              unit,
            )
          }
        />
        <select
          className="field w-32"
          aria-label="Notice period unit"
          value={unit}
          onChange={(e) => update(value ?? null, e.target.value as NoticeUnit)}
        >
          {UNITS.map(([option, text]) => (
            <option key={option} value={option}>
              {text}
            </option>
          ))}
        </select>
      </div>
    </FieldFrame>
  );
}
