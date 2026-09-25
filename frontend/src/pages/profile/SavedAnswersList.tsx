import { useEffect, useState } from "react";
import {
  type SavedAnswer,
  deleteSavedAnswer,
  fetchSavedAnswers,
  updateSavedAnswer,
} from "../../api";
import { Button } from "../../components/ui";
import { describe } from "../../lib/errors";
import { useToast } from "../../lib/toast";
import { useConfirm } from "../../state/confirmState";

function when(iso: string): string {
  const date = new Date(iso);
  return Number.isNaN(date.getTime()) ? iso : date.toLocaleDateString();
}

/**
 * Answers remembered from corrections in the review flow. Each saves on its own (they
 * live in the application database, not the profile), so edits here don't wait for the
 * page's save bar.
 */
export function SavedAnswersList() {
  const [answers, setAnswers] = useState<SavedAnswer[] | null>(null);
  const [drafts, setDrafts] = useState<Record<number, string>>({});
  const [busy, setBusy] = useState<number | null>(null);
  const toast = useToast();
  const { confirm } = useConfirm();

  useEffect(() => {
    fetchSavedAnswers()
      .then(setAnswers)
      .catch(() => setAnswers([]));
  }, []);

  async function save(item: SavedAnswer) {
    const text = (drafts[item.id] ?? item.answer).trim();
    if (!text) return;
    setBusy(item.id);
    try {
      const saved = await updateSavedAnswer(item.id, text);
      setAnswers((list) => (list ?? []).map((a) => (a.id === saved.id ? saved : a)));
      setDrafts(({ [item.id]: _dropped, ...rest }) => rest);
      toast.success("Saved answer updated.");
    } catch (err) {
      toast.error(describe(err).title);
    } finally {
      setBusy(null);
    }
  }

  async function forget(item: SavedAnswer) {
    const ok = await confirm({
      title: "Forget this answer?",
      message: `Forms asking “${item.label}” will be left for you (or the AI model) to answer again.`,
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

  return (
    <div className="mt-4">
      <h3 className="text-sm font-semibold">Remembered answers</h3>
      <p className="mt-1 text-xs text-ink-muted">
        When you correct an answer while reviewing a form, it is remembered and used the next time
        any form asks the same question. An answer that names a company is only reused for that
        company. Equal-opportunity answers, passwords and codes are never remembered.
      </p>
      {answers === null ? (
        <p className="mt-2 text-xs text-ink-muted">Loading…</p>
      ) : answers.length === 0 ? (
        <p className="mt-2 text-xs text-ink-muted">Nothing remembered yet.</p>
      ) : (
        <ul className="mt-2 space-y-3">
          {answers.map((item) => {
            const draft = drafts[item.id] ?? item.answer;
            const changed = draft.trim() !== item.answer;
            return (
              <li key={item.id} className="rounded-md border border-line p-3 text-sm">
                <label className="block">
                  <span className="font-medium">{item.label}</span>
                  <textarea
                    className="field mt-1"
                    value={draft}
                    rows={Math.min(6, Math.max(1, Math.ceil(draft.length / 80)))}
                    onChange={(e) => setDrafts((d) => ({ ...d, [item.id]: e.target.value }))}
                  />
                </label>
                <div className="mt-1 flex flex-wrap items-center justify-between gap-2 text-xs text-ink-muted">
                  <span>
                    {item.company ? `First answered for ${item.company}` : "Saved"}
                    {item.ats ? ` on ${item.ats}` : ""} · updated {when(item.updated_at)} · used{" "}
                    {item.uses} {item.uses === 1 ? "time" : "times"}
                  </span>
                  <span className="flex gap-2">
                    <Button
                      size="sm"
                      variant="secondary"
                      disabled={!changed || !draft.trim()}
                      loading={busy === item.id && changed}
                      onClick={() => void save(item)}
                    >
                      Save
                    </Button>
                    <Button
                      size="sm"
                      variant="ghost"
                      disabled={busy === item.id}
                      onClick={() => void forget(item)}
                    >
                      Forget
                    </Button>
                  </span>
                </div>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
