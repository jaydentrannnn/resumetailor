import { useEffect, useState } from "react";
import {
  type SavedAnswer,
  addSavedAnswer,
  deleteSavedAnswer,
  fetchSavedAnswers,
  updateSavedAnswer,
} from "../../api";
import { Button, Segmented } from "../../components/ui";
import {
  type AnswerSource,
  SOURCE_LABELS,
  filterAnswers,
  sourceCounts,
} from "../../lib/answerBook";
import { describe } from "../../lib/errors";
import { useToast } from "../../lib/toast";
import { useConfirm } from "../../state/confirmState";
import { AnswerBookItem } from "./AnswerBookItem";

/**
 * Every answer autofill reuses, in one list: your review corrections, answers you typed
 * on a form, custom answers, the AI's dropdown picks and question types it learned. Each
 * saves on its own (they live in the application database, not the profile).
 */
export function AnswerBook() {
  const [answers, setAnswers] = useState<SavedAnswer[] | null>(null);
  const [filter, setFilter] = useState<AnswerSource | "all">("all");
  const [busy, setBusy] = useState<number | null>(null);
  const toast = useToast();
  const { confirm } = useConfirm();

  useEffect(() => {
    fetchSavedAnswers()
      .then(setAnswers)
      .catch(() => setAnswers([]));
  }, []);

  async function save(item: SavedAnswer, text: string): Promise<boolean> {
    setBusy(item.id);
    try {
      const saved = await updateSavedAnswer(item.id, text);
      setAnswers((list) =>
        (list ?? []).map((a) => (a.id === saved.id ? { ...a, ...saved, differs: false } : a)),
      );
      toast.success("Answer updated.");
      return true;
    } catch (err) {
      toast.error(describe(err).title);
      return false;
    } finally {
      setBusy(null);
    }
  }

  async function forget(item: SavedAnswer) {
    const ok = await confirm({
      title: "Forget this answer?",
      message: `Forms asking “${item.label}” will be answered afresh, on every site.`,
      confirmLabel: "Forget",
      tone: "danger",
    });
    if (!ok) return;
    setBusy(item.id);
    try {
      setAnswers(await deleteSavedAnswer(item.id));
    } catch (err) {
      toast.error(describe(err).title);
    } finally {
      setBusy(null);
    }
  }

  const counts = sourceCounts(answers ?? []);
  const shown = filterAnswers(answers ?? [], filter);
  return (
    <div className="mt-3">
      <p className="text-xs text-ink-muted">
        Used when your profile doesn&apos;t cover a question. Answers you type into a form autofill
        left for you are saved here too. An answer that names a company is only reused for that
        company. Equal-opportunity answers, passwords and codes are never saved.
      </p>
      {counts.length > 1 && (
        <Segmented
          className="mt-3"
          label="Show answers from"
          value={filter}
          onChange={(id) => setFilter(id as AnswerSource | "all")}
          items={[
            { id: "all", label: `All ${answers?.length ?? 0}` },
            ...counts.map(([source, n]) => ({
              id: source,
              label: `${SOURCE_LABELS[source]} ${n}`,
            })),
          ]}
        />
      )}
      {answers === null ? (
        <p className="mt-2 text-xs text-ink-muted">Loading…</p>
      ) : answers.length === 0 ? (
        <p className="mt-2 text-xs text-ink-muted">
          Nothing saved yet. Add a question below, or fix a field autofill left for you.
        </p>
      ) : (
        <ul className="mt-2">
          {shown.map((item) => (
            <AnswerBookItem
              key={`${item.id}:${item.answer}`}
              item={item}
              busy={busy === item.id}
              onSave={(text) => save(item, text)}
              onForget={() => void forget(item)}
            />
          ))}
        </ul>
      )}
      <AddAnswer onAdded={setAnswers} />
    </div>
  );
}

/** "Add a question": a custom answer for a question no profile field covers. */
function AddAnswer({ onAdded }: { onAdded: (answers: SavedAnswer[]) => void }) {
  const [label, setLabel] = useState("");
  const [answer, setAnswer] = useState("");
  const [busy, setBusy] = useState(false);
  const toast = useToast();

  async function add() {
    setBusy(true);
    try {
      onAdded(await addSavedAnswer(label.trim(), answer.trim()));
      setLabel("");
      setAnswer("");
    } catch (err) {
      toast.error(describe(err).title);
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="mt-4 grid gap-2 border-t border-line pt-4 sm:grid-cols-[1fr_1fr_auto]">
      <input
        className="field"
        aria-label="Question"
        placeholder="Add a question, e.g. Are you willing to travel?"
        value={label}
        onChange={(e) => setLabel(e.target.value)}
      />
      <input
        className="field"
        aria-label="Answer"
        placeholder="Your answer"
        value={answer}
        onChange={(e) => setAnswer(e.target.value)}
      />
      <Button
        size="sm"
        variant="secondary"
        loading={busy}
        disabled={!label.trim() || !answer.trim()}
        onClick={() => void add()}
      >
        Add
      </Button>
    </div>
  );
}
