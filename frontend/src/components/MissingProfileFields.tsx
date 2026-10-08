import { Link } from "react-router-dom";
import type { MissingProfileField } from "../api";

/** Questions a fill recognised as a profile fact the profile leaves blank: each names
 *  the profile field to set once so every later form answers it without guessing. */
export function MissingProfileFields({ items }: { items: MissingProfileField[] }) {
  if (!items.length) return null;
  return (
    <section
      aria-label="Blank profile fields"
      className="mt-3 border-l-2 border-attn py-1 pl-3 text-xs"
    >
      <p className="font-semibold text-ink">Blank profile fields</p>
      <p className="text-ink-muted">
        This form asked for facts your profile leaves blank. Set them once and later fills answer
        them directly.
      </p>
      <ul className="mt-1 space-y-1">
        {items.map((item) => (
          <li key={item.key}>
            <Link className="rt-link font-medium" to={item.path}>
              {item.field_label}
            </Link>
            <span className="text-ink-muted">
              {" "}
              ({item.section}) · asked as{" "}
              {item.questions.map((question) => `“${question}”`).join(", ")} ·{" "}
              {item.answered ? "answered by the Autofill model this time" : "left blank"}
            </span>
          </li>
        ))}
      </ul>
    </section>
  );
}
