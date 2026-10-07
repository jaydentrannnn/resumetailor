import { useEffect, useState } from "react";
import { type AIChoice, fetchAIChoices, forgetAIChoice } from "../../api";
import { Button } from "../../components/ui";
import { describe } from "../../lib/errors";
import { useToast } from "../../lib/toast";

/**
 * Dropdown and radio picks the autofill model made for questions your profile does not
 * answer. Fills reuse them (so the same question is not asked again) until forgotten here.
 * They are tied to your current profile: editing it makes the model decide afresh.
 */
export function AIChoicesList() {
  const [choices, setChoices] = useState<AIChoice[] | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const toast = useToast();

  useEffect(() => {
    fetchAIChoices()
      .then(setChoices)
      .catch(() => setChoices([]));
  }, []);

  async function forget(choice: AIChoice) {
    setBusy(choice.key);
    try {
      setChoices(await forgetAIChoice(choice.key));
    } catch (err) {
      toast.error(describe(err).title);
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="mt-4">
      <h3 className="text-sm font-semibold">Choices the AI made</h3>
      <p className="mt-1 text-xs text-ink-muted">
        Picks the autofill model made for dropdowns and options your profile doesn’t answer. Forget
        one and the next fill asks the model again.
      </p>
      {choices === null ? (
        <p className="mt-2 text-xs text-ink-muted">Loading…</p>
      ) : choices.length === 0 ? (
        <p className="mt-2 text-xs text-ink-muted">None yet.</p>
      ) : (
        <ul className="mt-2 space-y-2">
          {choices.map((choice) => (
            <li
              key={choice.key}
              className="flex flex-wrap items-center justify-between gap-2 rounded-md border border-line p-3 text-sm"
            >
              <span>
                <span className="font-medium">{choice.label || "Untitled question"}</span>
                <span className="text-ink-muted"> → {choice.answer}</span>
                <span className="ml-2 rounded-full border border-line px-2 py-0.5 text-[11px] text-ink-muted">
                  AI
                </span>
              </span>
              <Button
                size="sm"
                variant="ghost"
                loading={busy === choice.key}
                onClick={() => void forget(choice)}
              >
                Forget
              </Button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
