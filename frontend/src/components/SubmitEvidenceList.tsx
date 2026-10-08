import { useEffect, useState } from "react";
import { fetchSubmitEvidence, submitEvidenceFileUrl, type SubmitEvidence } from "../api";
import { applicationStatusLabel } from "../lib/applicationStatus";
import { evidenceTime } from "../lib/submitEvidence";
import { Tile } from "./ui";

const FILE_LABELS: Record<string, string> = {
  "before.png": "Screenshot before",
  "after.png": "Screenshot after",
  "before.json": "Filled fields",
  "after.json": "Result",
};

/**
 * The audit trail of automatic submits (plan P4-S): what the form looked like and held
 * just before the click, and the page right after it.
 */
export function SubmitEvidenceList({ applicationId }: { applicationId: string }) {
  const [items, setItems] = useState<SubmitEvidence[] | null>(null);

  useEffect(() => {
    let alive = true;
    fetchSubmitEvidence(applicationId)
      .then((evidence) => alive && setItems(evidence))
      .catch(() => alive && setItems([]));
    return () => {
      alive = false;
    };
  }, [applicationId]);

  if (!items?.length) return null;
  return (
    <Tile title="Automatic submit evidence">
      <ul className="divide-y divide-line">
        {items.map((item) => (
          <li key={item.stamp} className="py-3 text-sm first:pt-0 last:pb-0">
            <p>
              <strong className="font-mono text-[13px] font-medium">
                {evidenceTime(item.stamp)}
              </strong>
              {item.status && <> · {applicationStatusLabel(item.status)}</>}
            </p>
            {item.url && <p className="break-all text-xs text-ink-muted">{item.url}</p>}
            <p className="mt-1 flex flex-wrap gap-3">
              {item.files.map((name) => (
                <a
                  key={name}
                  className="rt-link"
                  href={submitEvidenceFileUrl(applicationId, item.stamp, name)}
                  target="_blank"
                  rel="noreferrer"
                >
                  {FILE_LABELS[name] ?? name}
                </a>
              ))}
            </p>
          </li>
        ))}
      </ul>
    </Tile>
  );
}
