import { useState } from "react";
import type { AnswerDraft } from "../api";
import { answerApplicationQuestion } from "../api";
import { describe } from "../lib/errors";
import { CopyButton } from "./CopyButton";
import { Button, Card } from "./ui";

/** Draft a free-text application answer from the resume plus facts typed here; copy-only. */
export function AskAnswerCard({
  jobId,
  suggestions = [],
}: {
  jobId: string;
  suggestions?: string[];
}) {
  const [question, setQuestion] = useState("");
  const [context, setContext] = useState("");
  const [limit, setLimit] = useState("1500");
  const [draft, setDraft] = useState<AnswerDraft | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function generate(regenerate: boolean) {
    const maxChars = Math.min(10000, Math.max(50, Math.round(Number(limit)) || 1500));
    setBusy(true);
    setError(null);
    try {
      setDraft(await answerApplicationQuestion(jobId, { question, context, maxChars, regenerate }));
    } catch (e) {
      setDraft(null);
      setError(describe(e).detail);
    } finally {
      setBusy(false);
    }
  }

  const blocked = draft && !draft.answer && draft.offenders.length > 0;
  return (
    <Card
      title="Ask the AI"
      description="For questions autofill could not answer. It sees your full resume and work-authorization details, never contact info or salary. Anything you add below counts as true."
    >
      <div className="space-y-3">
        {suggestions.length > 0 && (
          <div className="text-sm">
            <p className="font-medium">Left unanswered by the last fill</p>
            <div className="mt-1 flex flex-wrap gap-2">
              {suggestions.map((s) => (
                <button
                  key={s}
                  type="button"
                  className="rt-row-action rounded-sm border border-ink/55 bg-field font-medium text-ink hover:border-ink hover:bg-sunken px-3 text-xs"
                  onClick={() => setQuestion(s)}
                >
                  {s}
                </button>
              ))}
            </div>
          </div>
        )}
        <label className="block text-sm">
          <span className="font-medium">Question</span>
          <textarea
            className="field mt-1"
            rows={3}
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
          />
        </label>
        <label className="block text-sm">
          <span className="font-medium">Extra context (optional)</span>
          <textarea
            className="field mt-1"
            rows={3}
            value={context}
            onChange={(e) => setContext(e.target.value)}
            placeholder="Anything true about you that the resume leaves out"
          />
        </label>
        <div className="flex flex-wrap items-end gap-3">
          <label className="block text-sm">
            <span className="font-medium">Character limit</span>
            <input
              type="number"
              className="field mt-1 w-28"
              min={50}
              max={10000}
              value={limit}
              onChange={(e) => setLimit(e.target.value)}
            />
          </label>
          <Button
            variant="primary"
            loading={busy}
            disabled={!question.trim()}
            onClick={() => void generate(false)}
          >
            Generate answer
          </Button>
        </div>
        {error && (
          <p role="alert" className="text-sm text-danger">
            {error}
          </p>
        )}
        {blocked && (
          <p role="alert" className="text-sm text-attn">
            No answer: the draft claimed things your resume and context do not support (
            {draft.offenders.join(", ")}). If they are true, add them to Extra context.
          </p>
        )}
        {draft && !draft.answer && !blocked && !error && (
          <p className="text-sm text-ink-muted">
            The material did not support a truthful answer. Add more context and try again.
          </p>
        )}
        {draft?.answer && (
          <div className="border-t border-line pt-4">
            <p className="whitespace-pre-wrap text-sm">{draft.answer}</p>
            <div className="mt-3 flex flex-wrap items-center gap-2 text-xs text-ink-muted">
              <span>{draft.answer.length} characters</span>
              <CopyButton label="Copy" text={draft.answer} />
              <Button size="sm" loading={busy} onClick={() => void generate(true)}>
                Regenerate
              </Button>
            </div>
            {draft.warnings.map((w) => (
              <p key={w} className="mt-1 text-xs text-attn">
                {w}
              </p>
            ))}
          </div>
        )}
      </div>
    </Card>
  );
}
