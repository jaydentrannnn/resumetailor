import type { ReactNode } from "react";
import type { InterviewPrep, PrepQuestion } from "../../../api";
import { StatusChip, type Tone } from "../../../components/ui";

const SOURCES: Record<PrepQuestion["source"], { label: string; tone: Tone }> = {
  requirement: { label: "From the posting", tone: "neutral" },
  gap: { label: "Not on your resume", tone: "attention" },
  feedback: { label: "Earlier round", tone: "neutral" },
  stage: { label: "Typical", tone: "muted" },
};

const STAR = [
  ["situation", "Situation"],
  ["task", "Task"],
  ["action", "Action"],
  ["result", "Result"],
] as const;

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="space-y-2 border-t border-line pt-3 first:border-t-0 first:pt-0">
      <h3 className="text-xs font-semibold uppercase tracking-wide text-ink-muted">{title}</h3>
      {children}
    </section>
  );
}

/**
 * One round's prep: likely questions (gap questions get no drafted answer), STAR stories
 * retold from the cited bullets, the sent claims an interviewer may dig into, and
 * questions to ask.
 */
export function PrepView({ prep }: { prep: InterviewPrep }) {
  return (
    <div className="space-y-4 text-[13px]">
      <p className="text-xs text-ink-muted">
        {prep.based_on} · {new Date(prep.made_at).toLocaleString()}
      </p>
      {prep.warnings.map((warning) => (
        <p key={warning} className="text-xs text-attn">
          {warning}
        </p>
      ))}
      <Section title="Likely questions">
        <ol className="space-y-2">
          {prep.questions.map((q) => (
            <li key={q.question} className="flex items-start gap-2">
              <span className="min-w-0 flex-1 text-ink">{q.question}</span>
              <StatusChip tone={SOURCES[q.source].tone} className="shrink-0">
                {SOURCES[q.source].label}
              </StatusChip>
            </li>
          ))}
        </ol>
        {prep.questions.some((q) => q.source === "gap") && (
          <p className="text-xs text-ink-muted">
            Answer "Not on your resume" questions honestly, in your own words.
          </p>
        )}
      </Section>
      {prep.stories.length > 0 && (
        <Section title="Stories to tell">
          {prep.stories.map((story) => (
            <div key={story.question + story.bullet_ids.join()} className="space-y-1">
              <p className="font-medium text-ink">{story.question}</p>
              <dl className="grid grid-cols-[5.5rem_1fr] gap-x-3 gap-y-1 text-ink-2">
                {STAR.filter(([key]) => story[key]).map(([key, label]) => (
                  <div key={key} className="contents">
                    <dt className="text-xs text-ink-muted">{label}</dt>
                    <dd>{story[key]}</dd>
                  </div>
                ))}
              </dl>
            </div>
          ))}
        </Section>
      )}
      {prep.probe_points.length > 0 && (
        <Section title="Be ready to explain">
          <ul className="list-disc space-y-1 pl-5 text-ink-2">
            {prep.probe_points.map((point) => (
              <li key={point.bullet_id}>{point.text}</li>
            ))}
          </ul>
        </Section>
      )}
      {prep.ask.length > 0 && (
        <Section title="Questions to ask">
          <ul className="list-disc space-y-1 pl-5 text-ink-2">
            {prep.ask.map((question) => (
              <li key={question}>{question}</li>
            ))}
          </ul>
        </Section>
      )}
    </div>
  );
}
