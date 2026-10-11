import type { CoverLetterSettings } from "../../../api";
import { COVER_BLOCKS, subjectExample } from "../../../lib/coverLetterSettings";
import { Field, Toggle } from "../../ui";

/** Which parts of the letter print, plus the subject-line pattern and the sign-off word. */
export function CoverBlocksSection({
  settings,
  onChange,
}: {
  settings: CoverLetterSettings;
  onChange: (next: CoverLetterSettings) => void;
}) {
  const { blocks } = settings;
  return (
    <section className="border-t border-line pt-4" aria-labelledby="cover-blocks">
      <h3 id="cover-blocks" className="font-semibold">
        Parts of the letter
      </h3>
      <p className="mt-1 text-xs text-ink-muted">The body paragraphs always print.</p>
      <div className="mt-3 space-y-3">
        {COVER_BLOCKS.map((block) => (
          <div key={block.id}>
            <Toggle
              label={block.label}
              help={block.help}
              checked={blocks[block.id]}
              onChange={(on) => onChange({ ...settings, blocks: { ...blocks, [block.id]: on } })}
            />
            {block.id === "subject" && blocks.subject && (
              <div className="ml-12 mt-2 max-w-sm">
                <Field
                  label="Subject pattern"
                  help={`{job_title} and {company} come from the posting. Reads: “${subjectExample(settings.subject_format)}”`}
                >
                  <input
                    className="field w-full"
                    value={settings.subject_format}
                    maxLength={200}
                    onChange={(e) => onChange({ ...settings, subject_format: e.target.value })}
                  />
                </Field>
              </div>
            )}
            {block.id === "closing" && blocks.closing && (
              <div className="ml-12 mt-2 max-w-[12rem]">
                <Field label="Sign-off word">
                  <input
                    className="field w-full"
                    value={settings.closing_text}
                    maxLength={80}
                    placeholder="Sincerely,"
                    onChange={(e) => onChange({ ...settings, closing_text: e.target.value })}
                  />
                </Field>
              </div>
            )}
          </div>
        ))}
      </div>
    </section>
  );
}
