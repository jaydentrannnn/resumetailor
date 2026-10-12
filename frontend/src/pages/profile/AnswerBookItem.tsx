import { useState } from "react";
import type { SavedAnswer } from "../../api";
import { Button, StatusChip } from "../../components/ui";
import { SOURCE_LABELS, answerSource } from "../../lib/answerBook";

function when(iso: string): string {
  const date = new Date(iso);
  return Number.isNaN(date.getTime()) ? iso : date.toLocaleDateString();
}

/** One Answer book entry: question, source badge, the answer (editable) and Forget. */
export function AnswerBookItem({
  item,
  busy,
  onSave,
  onForget,
}: {
  item: SavedAnswer;
  busy: boolean;
  onSave: (text: string) => Promise<boolean>;
  onForget: () => void;
}) {
  const [draft, setDraft] = useState(item.answer);
  const source = answerSource(item);
  const learned = source === "learned";
  const options = item.options ?? [];
  const changed = draft.trim() !== item.answer;
  return (
    <li className="border-t border-line py-3 text-sm">
      <label className="block">
        <span className="flex flex-wrap items-center gap-1.5">
          <span className="font-medium">{item.label || "Untitled question"}</span>
          <StatusChip tone="neutral" mark={false}>
            {SOURCE_LABELS[source]}
          </StatusChip>
          {(item.sites ?? []).map((site) => (
            <span key={site} className="font-mono text-[11px] text-ink-muted">
              {site}
            </span>
          ))}
          {item.differs && (
            <span className="text-[11px] text-attn">differs by site: showing the latest</span>
          )}
        </span>
        {learned ? (
          <span className="mt-1 block text-ink-muted">Recognised as: {item.answer}</span>
        ) : options.length > 0 ? (
          <select className="field mt-1" value={draft} onChange={(e) => setDraft(e.target.value)}>
            {!options.includes(draft) && <option value={draft}>{draft}</option>}
            {options.map((option) => (
              <option key={option}>{option}</option>
            ))}
          </select>
        ) : (
          <textarea
            className="field mt-1"
            value={draft}
            rows={Math.min(6, Math.max(1, Math.ceil(draft.length / 80)))}
            onChange={(e) => setDraft(e.target.value)}
          />
        )}
      </label>
      <div className="mt-1 flex flex-wrap items-center justify-between gap-2 text-xs text-ink-muted">
        <span>
          {item.company ? `Last answered for ${item.company} · ` : ""}updated{" "}
          {when(item.updated_at)} · used {item.uses} {item.uses === 1 ? "time" : "times"}
        </span>
        <span className="flex gap-2">
          {!learned && (
            <Button
              size="sm"
              variant="secondary"
              disabled={!changed || !draft.trim()}
              loading={busy && changed}
              onClick={() => void onSave(draft.trim())}
            >
              Save
            </Button>
          )}
          <Button size="sm" variant="ghost" disabled={busy} onClick={onForget}>
            Forget
          </Button>
        </span>
      </div>
    </li>
  );
}
