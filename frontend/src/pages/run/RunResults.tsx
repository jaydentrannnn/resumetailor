import { CoverLetterDetails } from "../../components/CoverLetterPanel";
import { ExperienceCard } from "../../components/ExperienceCard";
import { GenerateExperienceCard } from "../../components/GenerateExperienceCard";
import { RegenerateExpansionButton } from "../../components/RegenerateExpansionButton";
import { SkillsCard } from "../../components/SkillsCard";
import { regenerateCoverLetter } from "../../api";
import { useRunState } from "../../state/runState";
import { BulletReview } from "./BulletReview";
import { ReportCard } from "./ReportCard";

export type ResultPane = "report" | "bullets" | "content";

/** "Halcyon Health · Data Analyst Intern · Oct 7, 1:12 PM" for the shown run. */
export function runMeta(
  entry: { title?: string; company?: string; created_at?: string } | undefined,
  fallback: string | undefined,
): string {
  const when = entry?.created_at ? new Date(entry.created_at) : null;
  return [
    entry?.company,
    entry?.title || fallback,
    when && !Number.isNaN(when.getTime())
      ? when.toLocaleString(undefined, {
          month: "short",
          day: "numeric",
          hour: "numeric",
          minute: "2-digit",
        })
      : "",
  ]
    .filter(Boolean)
    .join(" · ");
}

/**
 * The shown run's report, bullet review or application content (skills, experience
 * descriptions, the cover letter's text) in the Tailor page's left pane; the documents
 * themselves are in the viewer beside it. Each card renders `embedded`.
 */
export function RunResults({
  jobId,
  pane,
  onResumeChanged,
  onCoverChanged,
}: {
  jobId: string;
  pane: ResultPane;
  /** A bullet edit re-rendered the resume. */
  onResumeChanged: () => void;
  /** The cover letter was regenerated. */
  onCoverChanged: () => void;
}) {
  const {
    report,
    refreshReport,
    expansion,
    setExpansion,
    skills,
    coverLetter,
    setCoverLetter,
    busy,
  } = useRunState();

  if (pane === "report")
    return report ? (
      <ReportCard report={report} embedded />
    ) : (
      <p className="text-sm text-ink-muted">A report has not been saved for this run.</p>
    );
  if (pane === "bullets")
    return (
      <BulletReview
        jobId={jobId}
        ready={!busy}
        embedded
        onSaved={() => {
          onResumeChanged();
          void refreshReport();
        }}
      />
    );
  return (
    <div className="space-y-6">
      {skills && <SkillsCard plan={skills} gaps={report?.gaps ?? []} jobId={jobId} embedded />}
      <div className={skills ? "border-t border-line pt-6" : undefined}>
        {expansion ? (
          <ExperienceCard
            expansion={expansion}
            jobId={jobId}
            embedded
            extraActions={
              <RegenerateExpansionButton
                jobId={jobId}
                disabled={busy}
                onRegenerated={setExpansion}
              />
            }
          />
        ) : (
          <GenerateExperienceCard jobId={jobId} ready={!busy} onGenerated={setExpansion} embedded />
        )}
      </div>
      {coverLetter && (
        <section aria-labelledby="cover-letter-heading" className="border-t border-line pt-6">
          <h3 id="cover-letter-heading" className="rt-tile-title mb-3">
            Cover letter
          </h3>
          <CoverLetterDetails
            letter={coverLetter}
            onRegenerate={async (instruction) => {
              setCoverLetter(await regenerateCoverLetter(jobId, instruction));
              onCoverChanged();
            }}
          />
        </section>
      )}
    </div>
  );
}
