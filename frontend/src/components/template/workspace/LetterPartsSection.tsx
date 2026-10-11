import { useState, type ReactNode } from "react";
import type { CoverLetterField, CoverLetterSettings } from "../../../api";
import { LETTER_PARTS, subjectExample } from "../../../lib/coverLetterSettings";
import { Field, TileSection } from "../../ui";
import { LetterheadOptions } from "./LetterheadOptions";
import { LetterPartRow } from "./LetterPartRow";

const OPEN_KEY = "rt.coverParts.open";

function readOpen(): string[] {
  try {
    const raw = window.localStorage.getItem(OPEN_KEY);
    return raw ? (JSON.parse(raw) as string[]) : [];
  } catch {
    return [];
  }
}

function writeOpen(ids: string[]) {
  try {
    window.localStorage.setItem(OPEN_KEY, JSON.stringify(ids));
  } catch {
    /* private window: open parts just aren't remembered */
  }
}

/**
 * The parts of the letter in the order they print, so the list reads down the page like
 * the letter beside it. An own letter's letterhead is part of its file, so that part is
 * left out. Which parts are open is remembered on this device.
 */
export function LetterPartsSection({
  settings,
  fields,
  onChange,
}: {
  settings: CoverLetterSettings;
  fields: CoverLetterField[];
  onChange: (next: CoverLetterSettings) => void;
}) {
  const [open, setOpen] = useState<string[]>(readOpen);
  const own = settings.design === "own";
  const toggle = (id: string, next: boolean) => {
    const ids = next ? [...open.filter((x) => x !== id), id] : open.filter((x) => x !== id);
    setOpen(ids);
    writeOpen(ids);
  };

  const options: Record<string, ReactNode> = {
    letterhead: <LetterheadOptions settings={settings} fields={fields} onChange={onChange} />,
    subject: (
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
    ),
    closing: (
      <Field label="Sign-off word">
        <input
          className="field w-full"
          value={settings.closing_text}
          maxLength={80}
          placeholder="Sincerely,"
          onChange={(e) => onChange({ ...settings, closing_text: e.target.value })}
        />
      </Field>
    ),
  };

  return (
    <TileSection title="Parts of the letter">
      <ul className="text-sm">
        {LETTER_PARTS.filter((part) => !(own && part.id === "letterhead")).map((part) => (
          <LetterPartRow
            key={part.id}
            part={part}
            settings={settings}
            fields={fields}
            open={open.includes(part.id)}
            onOpen={(next) => toggle(part.id, next)}
            onChange={onChange}
          >
            {options[part.id]}
          </LetterPartRow>
        ))}
      </ul>
    </TileSection>
  );
}
