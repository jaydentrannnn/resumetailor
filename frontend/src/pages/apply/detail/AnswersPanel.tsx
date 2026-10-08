import type { ApplicationRow, JobStatus, Packet } from "../../../api";
import { AskAnswerCard } from "../../../components/AskAnswerCard";
import { ExperienceCard } from "../../../components/ExperienceCard";
import { SkillsCard } from "../../../components/SkillsCard";
import { Tile } from "../../../components/ui";
import { unansweredQuestions } from "../../../lib/askQuestions";

/**
 * Answers: ask the AI about a question the fill left unanswered, the tailored skills and
 * experience, what the last fill typed, and the prepared answers saved with the packet.
 */
export function AnswersPanel({
  app,
  job,
  packet,
}: {
  app: ApplicationRow;
  job: JobStatus | null;
  packet: Packet | null | undefined;
}) {
  const written = Object.entries(app.fill?.long_text_answers ?? {});
  return (
    <div className="space-y-4">
      <p className="text-xs text-ink-muted">
        Prepared content was saved with this application and may differ from later Profile edits.
      </p>
      {app.job_id && job?.status === "succeeded" ? (
        <AskAnswerCard jobId={app.job_id} suggestions={unansweredQuestions(app.fill)} />
      ) : (
        <Tile>
          <p className="text-sm text-ink-muted">
            Tailor this application first to ask the AI a question.
          </p>
        </Tile>
      )}
      {job?.skills && app.job_id && (
        <SkillsCard plan={job.skills} gaps={job.report?.gaps ?? []} jobId={app.job_id} />
      )}
      {job?.expansion && app.job_id && (
        <ExperienceCard expansion={job.expansion} jobId={app.job_id} />
      )}
      {written.length > 0 && (
        <Tile title="Written answers" description="What the last fill typed into the form.">
          <div className="divide-y divide-line">
            {written.map(([question, answer]) => (
              <div className="py-3 text-sm first:pt-0 last:pb-0" key={question}>
                <p className="font-medium text-ink">{question}</p>
                <p className="mt-1 whitespace-pre-wrap text-ink-muted">{answer}</p>
              </div>
            ))}
          </div>
        </Tile>
      )}
      {packet && (
        <Tile title="Prepared answers">
          <div className="divide-y divide-line">
            {Object.entries(packet.fields)
              .filter(([key]) => !/password|credential|secret/i.test(key))
              .map(([key, value]) => (
                <details className="py-2.5 text-sm first:pt-0 last:pb-0" key={key}>
                  <summary className="cursor-pointer font-medium text-ink">{key}</summary>
                  <p className="mt-1 whitespace-pre-wrap text-ink-muted">{value}</p>
                </details>
              ))}
          </div>
        </Tile>
      )}
    </div>
  );
}
