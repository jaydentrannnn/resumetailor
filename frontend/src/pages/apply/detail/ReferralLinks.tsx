import type { ApplicationRow } from "../../../api";
import { referralSearches } from "../../../lib/referralLinks";

/**
 * Someone to ask for a referral: LinkedIn people searches for the company's recruiters and
 * for people in this role. They open in the browser; the app never visits LinkedIn.
 */
export function ReferralLinks({ app }: { app: ApplicationRow }) {
  const searches = referralSearches(app.company, app.role);
  if (!searches.length) return null;
  return (
    <div className="mt-5 border-t border-line pt-4 text-sm">
      <p className="font-semibold text-ink">Ask for a referral</p>
      <p className="mt-1 text-ink-muted">
        Search LinkedIn for{" "}
        {searches.map((search, index) => (
          <span key={search.url}>
            {index > 0 && " or "}
            <a className="rt-link" href={search.url} target="_blank" rel="noreferrer">
              {search.label}
            </a>
          </span>
        ))}
        .
      </p>
    </div>
  );
}
