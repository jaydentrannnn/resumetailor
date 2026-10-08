import { buttonClass } from "../../lib/buttonClass";
import type { TemplateAnalyzeResponse } from "../../api";
import { issueHelp } from "../../lib/templateIssues";
import { StatusChip } from "../ui";

type Issue = TemplateAnalyzeResponse["issues"][number];

/** Fixes the app can make itself, offered next to the issue that needs them. */
export type IssueActions = {
  /** Re-analyze with typed bullets turned into a real list. */
  onConvertBullets?: () => void;
  /** Import the file's words into the master resume without using its layout. */
  onImportContent?: () => void;
  busy?: boolean;
};

/**
 * Analyzer findings in plain language: what it means, how to fix it in Word or Google
 * Docs, and the analyzer's exact wording under "Details" for anyone who wants it.
 */
export function IssueList({
  issues,
  tone,
  actions,
}: {
  issues: Issue[];
  tone: "danger" | "warn";
  actions?: IssueActions;
}) {
  return (
    <div className="border-t border-line pt-4">
      <StatusChip tone={tone === "danger" ? "failed" : "attention"}>
        {tone === "danger" ? "Needs fixing before install" : "Worth knowing"}
      </StatusChip>
      <ul className="mt-2 space-y-3">
        {issues.map((issue) => {
          const help = issueHelp(issue.code);
          return (
            <li key={issue.code + issue.message} className="space-y-2 text-ink">
              <StatusChip tone={tone === "danger" ? "failed" : "attention"}>
                {help.title}
              </StatusChip>
              <p className="text-ink-muted">{help.why}</p>
              {(help.word || help.docs || help.app) && (
                <dl className="mt-1 space-y-0.5 text-xs">
                  {help.word && (
                    <div>
                      <dt className="inline font-semibold">In Word: </dt>
                      <dd className="inline">{help.word}</dd>
                    </div>
                  )}
                  {help.docs && (
                    <div>
                      <dt className="inline font-semibold">In Google Docs: </dt>
                      <dd className="inline">{help.docs}</dd>
                    </div>
                  )}
                  {help.app && (
                    <div>
                      <dt className="inline font-semibold">Here: </dt>
                      <dd className="inline">{help.app}</dd>
                    </div>
                  )}
                </dl>
              )}
              {issue.code === "manual_bullets" && actions?.onConvertBullets && (
                <button
                  type="button"
                  disabled={actions.busy}
                  onClick={actions.onConvertBullets}
                  className={buttonClass("secondary", "sm", "mt-2")}
                >
                  Convert typed bullets to a real list
                </button>
              )}
              {help.useDefault && actions?.onImportContent && (
                <button
                  type="button"
                  disabled={actions.busy}
                  onClick={actions.onImportContent}
                  className={buttonClass("secondary", "sm", "mt-2")}
                >
                  Import the content and pick a starter template
                </button>
              )}
              <details className="mt-1 text-xs text-ink-muted">
                <summary className="cursor-pointer">Details</summary>
                <p className="mt-1 font-mono">
                  {issue.code}: {issue.message}
                </p>
              </details>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
