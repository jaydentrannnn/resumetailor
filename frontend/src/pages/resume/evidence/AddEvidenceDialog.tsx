import { useState } from "react";
import type { EvidenceAddRequest, EvidenceProposal, EvidenceSource } from "../../../api";
import { Button, Modal } from "../../../components/ui";
import {
  entryOptions,
  projectSections,
  schools,
  skillChoices,
  skillGroups,
} from "../../../lib/evidence";
import type { MasterResume } from "../../../lib/resumeEdit";

const select = "field mt-1 w-full text-sm";

/**
 * Add one item to the resume as the student settles it: edit the words, choose where it
 * goes, and tick which skills the bullet carries as Extra skills (none by default). What
 * is saved is the student's own edit.
 */
export function AddEvidenceDialog({
  proposal,
  source,
  resume,
  busy,
  onClose,
  onSave,
}: {
  proposal: EvidenceProposal;
  source: EvidenceSource | undefined;
  resume: MasterResume | null;
  busy: boolean;
  onClose: () => void;
  onSave: (body: EvidenceAddRequest) => void;
}) {
  const entries = entryOptions(resume);
  const groups = skillGroups(resume);
  const sections = projectSections(resume);
  const [text, setText] = useState(proposal.text);
  const [target, setTarget] = useState(proposal.target_entry_id || entries[0]?.id || "");
  const [group, setGroup] = useState(groups[0] ?? "");
  const [school, setSchool] = useState(0);
  const [section, setSection] = useState(sections[0]?.id ?? "");
  const [name, setName] = useState(proposal.new_project?.name ?? "");
  const [ticked, setTicked] = useState<string[]>([]);
  const choices = skillChoices(proposal, source);
  const withBullet = proposal.kind === "bullet" || proposal.kind === "project";

  const save = () => {
    const body: EvidenceAddRequest = { text: text.trim() };
    if (proposal.kind === "bullet") body.target_entry_id = target;
    if (proposal.kind === "project" && proposal.new_project)
      Object.assign(body, {
        section_id: section,
        new_project: { ...proposal.new_project, name: name.trim() },
      });
    if (proposal.kind === "skill") body.skill_group = group;
    if (proposal.kind === "coursework") body.education_index = school;
    if (withBullet) body.skills = ticked;
    onSave(body);
  };
  const missing =
    !text.trim() ||
    (proposal.kind === "bullet" && !target) ||
    (proposal.kind === "project" && (!name.trim() || !section)) ||
    (proposal.kind === "skill" && !group);

  return (
    <Modal title="Add to resume" onClose={onClose}>
      <div className="mt-4 space-y-3 text-sm">
        <p className="text-xs italic text-ink-muted">From the source: “{proposal.excerpt}”</p>
        {proposal.question && (
          <p className="text-xs text-ink-2">
            <span className="font-medium">Answer first:</span> {proposal.question} Edit the words to
            say only what you did.
          </p>
        )}
        {proposal.kind === "project" && (
          <label className="block text-xs">
            <span className="font-medium">Project name</span>
            <input className={select} value={name} onChange={(e) => setName(e.target.value)} />
          </label>
        )}
        <label className="block text-xs">
          <span className="font-medium">
            {withBullet ? "Bullet" : proposal.kind === "skill" ? "Skill" : "Course"}
          </span>
          <textarea
            className={`${select} min-h-20`}
            value={text}
            onChange={(e) => setText(e.target.value)}
          />
        </label>
        {proposal.kind === "bullet" && (
          <label className="block text-xs">
            <span className="font-medium">Goes to</span>
            <select className={select} value={target} onChange={(e) => setTarget(e.target.value)}>
              {entries.map((entry) => (
                <option key={entry.id} value={entry.id}>
                  {entry.label}
                </option>
              ))}
            </select>
          </label>
        )}
        {proposal.kind === "project" && sections.length > 1 && (
          <label className="block text-xs">
            <span className="font-medium">Section</span>
            <select className={select} value={section} onChange={(e) => setSection(e.target.value)}>
              {sections.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.title}
                </option>
              ))}
            </select>
          </label>
        )}
        {proposal.kind === "skill" && (
          <label className="block text-xs">
            <span className="font-medium">Skills group</span>
            <select className={select} value={group} onChange={(e) => setGroup(e.target.value)}>
              {groups.map((g) => (
                <option key={g}>{g}</option>
              ))}
            </select>
          </label>
        )}
        {proposal.kind === "coursework" && (
          <label className="block text-xs">
            <span className="font-medium">School</span>
            <select
              className={select}
              value={school}
              onChange={(e) => setSchool(Number(e.target.value))}
            >
              {schools(resume).map((s, i) => (
                <option key={`${s}-${i}`} value={i}>
                  {s}
                </option>
              ))}
            </select>
          </label>
        )}
        {withBullet && choices.length > 0 && (
          <fieldset className="text-xs">
            <legend className="font-medium">Extra skills you really used (optional)</legend>
            <div className="mt-1 flex flex-wrap gap-3">
              {choices.map((skill) => (
                <label key={skill} className="flex items-center gap-1.5">
                  <input
                    type="checkbox"
                    checked={ticked.includes(skill)}
                    onChange={(e) =>
                      setTicked(
                        e.target.checked ? [...ticked, skill] : ticked.filter((s) => s !== skill),
                      )
                    }
                  />
                  {skill}
                </label>
              ))}
            </div>
          </fieldset>
        )}
        <div className="flex justify-end gap-2 pt-2">
          <Button size="sm" variant="plain" onClick={onClose}>
            Cancel
          </Button>
          <Button
            size="sm"
            variant="primary"
            loading={busy}
            disabled={busy || missing}
            onClick={save}
          >
            Add to resume
          </Button>
        </div>
      </div>
    </Modal>
  );
}
