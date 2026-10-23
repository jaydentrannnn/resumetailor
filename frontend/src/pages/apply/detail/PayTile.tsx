import { Link } from "react-router-dom";
import type { ApplicationPay, PayGroup, PaySplit } from "../../../api";
import { Tile } from "../../../components/ui";
import { dateSpan, money, payRange, splitHeading } from "../../../lib/pay";

function Split({ split }: { split: PaySplit }) {
  const { currency, period } = split;
  return (
    <div className="space-y-1">
      <p className="text-xs font-medium text-ink-2">
        {splitHeading(currency, period)} · {split.n} {split.n === 1 ? "figure" : "figures"}
      </p>
      {split.median != null ? (
        <p className="font-mono text-[13px] text-ink">
          25th {money(split.p25!, currency)} · median {money(split.median, currency)} · 75th{" "}
          {money(split.p75!, currency)}
        </p>
      ) : (
        <ul className="space-y-0.5 text-[13px]">
          {split.figures.map((figure, index) => (
            <li key={index} className="flex flex-wrap gap-x-2" title={figure.excerpt || undefined}>
              <span className="font-mono text-ink">
                {payRange(figure.low, figure.high, currency, period)}
              </span>
              <span className="min-w-0 truncate text-ink-muted">
                {[figure.company, figure.role, figure.location].filter(Boolean).join(" · ")}
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function Group({ group }: { group: PayGroup }) {
  const span = dateSpan(group.first_on, group.last_on);
  return (
    <section className="space-y-2 border-t border-line pt-3 first:border-t-0 first:pt-0">
      <div>
        <h3 className="text-sm font-semibold text-ink">{group.label}</h3>
        <p className="text-xs text-ink-muted">
          From {group.sources.join(", ")}
          {span ? ` · ${span}` : ""}
        </p>
      </div>
      {group.splits.map((split) => (
        <Split key={`${split.currency}-${split.period}`} split={split} />
      ))}
    </section>
  );
}

/**
 * Posted ranges for roles like this one: the same company, the same family and level
 * nearby, and anywhere. Hourly and yearly figures stay apart; percentiles show only
 * from five figures up. Never an estimate of an offer.
 */
export function PayTile({ pay }: { pay: ApplicationPay | null }) {
  if (!pay) return null;
  return (
    <Tile title="Pay for similar roles">
      <p className="mb-4 text-xs text-ink-muted">
        Posted ranges from your saved postings and imported pay data, not an estimate of an offer.
        This role reads as {pay.level.toLowerCase()}, {pay.family.toLowerCase()}.
      </p>
      {pay.groups.length ? (
        <div className="space-y-4">
          {pay.groups.map((group) => (
            <Group key={group.kind} group={group} />
          ))}
        </div>
      ) : (
        <p className="text-sm text-ink-muted">
          No similar role with stated pay yet.{" "}
          <Link className="underline" to="/settings?tab=data">
            Import pay data
          </Link>{" "}
          to compare more.
        </p>
      )}
    </Tile>
  );
}
