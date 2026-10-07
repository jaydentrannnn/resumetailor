import { useState } from "react";
import { mergeCustomAnswer } from "../../api";
import { Button } from "../../components/ui";
import { fieldLabel } from "../../lib/profileForm";
import { useToast } from "../../lib/toast";
import { useApplicantProfile } from "../../state/applicantProfileState";

/**
 * Canned answers for questions no profile field covers. One whose question restates a
 * built-in field (18 or older, start date, ...) is flagged with a button that folds it
 * into that field; new entries can be added and old ones removed.
 */
export function CustomAnswers() {
  const applicant = useApplicantProfile();
  const toast = useToast();
  const draft = applicant.draft;
  const [question, setQuestion] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  if (!draft) return null;
  const answers = draft.custom_answers ?? {};
  const setAnswers = (next: Record<string, string>) =>
    applicant.setDraft({ ...draft, custom_answers: next });

  async function merge(text: string) {
    setBusy(text);
    try {
      // Unsaved edits would be lost when the server's copy replaces the draft.
      if (applicant.dirty && !(await applicant.save())) return;
      applicant.accept(await mergeCustomAnswer(text));
      toast.success("Moved into your profile");
    } catch (reason) {
      toast.error(String(reason));
    } finally {
      setBusy(null);
    }
  }
  function add() {
    const text = question.trim();
    if (!text || text in answers) return;
    setAnswers({ ...answers, [text]: "" });
    setQuestion("");
  }
  return (
    <div className="mt-4">
      <h3 className="text-sm font-semibold">Custom answers</h3>
      <p className="mt-1 text-xs text-ink-muted">
        For questions the fields above don’t cover. Remembered answers below are used first.
      </p>
      {Object.entries(answers).map(([text, answer]) => {
        const field = applicant.duplicates[text];
        const rest = Object.fromEntries(Object.entries(answers).filter(([key]) => key !== text));
        return (
          <div key={text} className="mt-2 text-sm">
            <div className="flex items-baseline justify-between gap-2">
              <label htmlFor={`ca-${text}`}>{text}</label>
              <button
                type="button"
                className="text-xs text-ink-muted underline hover:text-danger"
                onClick={() => setAnswers(rest)}
              >
                Remove
              </button>
            </div>
            <textarea
              id={`ca-${text}`}
              className="field mt-1"
              value={answer}
              onChange={(e) => setAnswers({ ...answers, [text]: e.target.value })}
            />
            {field && (
              <p className="mt-1 flex flex-wrap items-center gap-2 text-xs text-warn">
                This repeats “{fieldLabel(field)}” above.
                <Button
                  size="sm"
                  variant="ghost"
                  loading={busy === text}
                  onClick={() => void merge(text)}
                >
                  Move into that field
                </Button>
              </p>
            )}
          </div>
        );
      })}
      <div className="mt-3 flex gap-2">
        <input
          className="field flex-1"
          aria-label="New custom answer question"
          placeholder="Add a question, e.g. Are you willing to travel?"
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          onKeyDown={(e) => {
            if (e.key !== "Enter") return;
            e.preventDefault();
            add();
          }}
        />
        <Button size="sm" variant="ghost" disabled={!question.trim()} onClick={add}>
          Add
        </Button>
      </div>
    </div>
  );
}
