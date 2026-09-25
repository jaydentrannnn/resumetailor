import { Link } from "react-router-dom";
import type { ProfileGap } from "../api";

/** One line naming the blank profile fields forms ask for, linking to where to set them. */
export function ProfileGapsNotice({ gaps }: { gaps: ProfileGap[] }) {
  if (!gaps.length) return null;
  const shown = gaps
    .slice(0, 4)
    .map((gap) => gap.label)
    .join(", ");
  const more = gaps.length > 4 ? ` and ${gaps.length - 4} more` : "";
  return (
    <p role="status" className="rounded-md border border-warn/50 bg-panel px-3 py-2 text-sm">
      Autofill will skip questions your profile leaves blank: {shown}
      {more}.{" "}
      <Link className="text-accent underline" to={gaps[0].path}>
        Set them in your profile
      </Link>
    </p>
  );
}
