import { useEffect, useId, useState } from "react";
import type { AppConfig, JobSettings } from "../../api";
import { Field, Toggle } from "../../components/Field";
import { IncludePanel } from "../../components/IncludePanel";
import { RunStyleRules } from "./RunStyleRules";
import { SectionBalance } from "./SectionBalance";

const OPEN_KEY = "rt.runOptions.open.";

function readOpen(workspaceId: string): boolean {
  try {
    return window.localStorage.getItem(OPEN_KEY + workspaceId) === "1";
  } catch {
    return false;
  }
}

type FormProps = {
  config: AppConfig | null;
  settings: JobSettings;
  onChange: (s: JobSettings) => void;
  disabled: boolean;
};

/** Parse a number-input's raw string, clamped to [min, max]. Returns `undefined`
 * for an empty or unparseable value so the caller can skip the write entirely —
 * `Number("")` is `0`, which would otherwise silently persist and 422 on save. */
function parseClamped(raw: string, min: number, max: number): number | undefined {
  if (raw.trim() === "") return undefined;
  const n = Number(raw);
  if (!Number.isFinite(n)) return undefined;
  return Math.min(max, Math.max(min, Math.round(n)));
}

/**
 * The run options form, simple first: page count and the cover letter are always
 * visible; everything else sits under "More options", whose open state is remembered
 * per profile. Shown inside the Options tile once "Change" is pressed.
 */
export function RunOptionsForm({
  config,
  settings,
  onChange,
  disabled,
  workspaceId,
}: FormProps & { workspaceId: string }) {
  const [open, setOpen] = useState(() => readOpen(workspaceId));
  const moreId = useId();
  useEffect(() => {
    try {
      window.localStorage.setItem(OPEN_KEY + workspaceId, open ? "1" : "0");
    } catch {
      /* storage unavailable: the disclosure just is not remembered */
    }
  }, [open, workspaceId]);

  function set<K extends keyof JobSettings>(key: K, value: JobSettings[K]) {
    onChange({ ...settings, [key]: value });
  }

  return (
    <>
      <fieldset disabled={disabled} className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <Field label="Pages">
          <select
            className="field"
            value={settings.pages}
            onChange={(e) => set("pages", Number(e.target.value))}
          >
            {[1, 2, ...(settings.pages > 2 ? [settings.pages] : [])].map((n) => (
              <option key={n} value={n}>
                {n} page{n === 1 ? "" : "s"}
              </option>
            ))}
          </select>
        </Field>
        <div className="sm:pt-6">
          <Toggle
            label="Application-form text"
            help="Paragraphs for each job, ready to paste into application forms. Apply turns this on for its own runs."
            checked={!settings.no_expand}
            onChange={(v) => set("no_expand", !v)}
          />
        </div>
        {/* The tone sits beside its switch; the cell stays (empty) so the switch keeps its column. */}
        <div className="hidden sm:block">
          {settings.cover_letter && <CoverTone settings={settings} set={set} />}
        </div>
        <div className="sm:pt-6">
          <Toggle
            label="Cover letter"
            help="Also write a cover letter from the tailored resume."
            checked={settings.cover_letter}
            onChange={(v) => set("cover_letter", v)}
          />
        </div>
        {settings.cover_letter && (
          <div className="sm:hidden">
            <CoverTone settings={settings} set={set} />
          </div>
        )}
      </fieldset>

      <div className="mt-5 border-t border-line pt-4">
        <button
          type="button"
          onClick={() => setOpen((o) => !o)}
          aria-expanded={open}
          aria-controls={moreId}
          className="text-[13px] font-semibold text-ink hover:text-ink-2"
        >
          More options {open ? "▾" : "▸"}
        </button>
        {open && (
          <div id={moreId} className="mt-4 grid gap-8 lg:grid-cols-2">
            <MoreOptions
              config={config}
              settings={settings}
              onChange={onChange}
              disabled={disabled}
            />
            <fieldset disabled={disabled} className="contents">
              <IncludePanel settings={settings} onChange={onChange} />
            </fieldset>
          </div>
        )}
      </div>
    </>
  );
}

const SLIDER = "w-full accent-[var(--color-accent)]";

/** Selection sizing, fill targets, the opt-out stages, and the writing style rules. */
function MoreOptions({ config, settings, onChange, disabled }: FormProps) {
  function set<K extends keyof JobSettings>(key: K, value: JobSettings[K]) {
    onChange({ ...settings, [key]: value });
  }

  const coverOn = settings.cover_letter && !settings.no_cover_letter;

  return (
    <fieldset disabled={disabled} className="min-w-0 space-y-3">
      <legend className="sr-only">More options</legend>
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <Field label="Jobs to include" help="Most relevant first.">
          <input
            type="number"
            min={1}
            max={10}
            value={settings.experience ?? config?.experience ?? 3}
            onChange={(e) => {
              const next = parseClamped(e.target.value, 1, 10);
              if (next !== undefined) set("experience", next);
            }}
            className="field"
          />
        </Field>
        <Field label="Projects to include" help="Ranked separately from jobs.">
          <input
            type="number"
            min={1}
            max={10}
            value={settings.projects ?? config?.projects ?? 2}
            onChange={(e) => {
              const next = parseClamped(e.target.value, 1, 10);
              if (next !== undefined) set("projects", next);
            }}
            className="field"
          />
        </Field>
      </div>
      {coverOn && <CoverAngles settings={settings} set={set} />}
      <BulletBudget config={config} settings={settings} onChange={onChange} />
      <Field
        label="Max bullets per entry"
        help="Cap on how many bullets any single job or project may take."
      >
        <select
          value={settings.max_bullets_per_entry ?? ""}
          onChange={(e) =>
            set("max_bullets_per_entry", e.target.value === "" ? null : Number(e.target.value))
          }
          className="field"
        >
          <option value="">No limit</option>
          {[2, 3, 4, 5, 6].map((n) => (
            <option key={n} value={n}>
              {n}
            </option>
          ))}
        </select>
      </Field>
      <StageToggles settings={settings} set={set} />
      <RunStyleRules config={config} settings={settings} set={set} />
    </fieldset>
  );
}

type Setter = <K extends keyof JobSettings>(key: K, value: JobSettings[K]) => void;

function CoverTone({ settings, set }: { settings: JobSettings; set: Setter }) {
  return (
    <Field label="Cover letter tone">
      <select
        value={settings.cover_angles.tone}
        onChange={(e) =>
          set("cover_angles", {
            ...settings.cover_angles,
            tone: e.target.value as JobSettings["cover_angles"]["tone"],
          })
        }
        className="field"
      >
        <option value="">Default</option>
        <option value="formal">Formal</option>
        <option value="direct">Direct</option>
        <option value="conversational">Conversational</option>
        <option value="mirror">Match the posting</option>
      </select>
    </Field>
  );
}

/** Optional cover-letter angles, shown while a cover letter is on. */
function CoverAngles({ settings, set }: { settings: JobSettings; set: Setter }) {
  return (
    <div className="space-y-3 border-y border-line py-3">
      <p className="text-xs text-ink-muted">
        Optional cover letter angles for this application. Leave blank for the default letter.
      </p>
      {(
        [
          ["why_company", "Why this company"],
          ["problem", "Problem to solve"],
          ["approach", "Your approach"],
        ] as const
      ).map(([key, label]) => (
        <Field key={key} label={label}>
          <textarea
            value={settings.cover_angles[key]}
            onChange={(e) =>
              set("cover_angles", { ...settings.cover_angles, [key]: e.target.value })
            }
            rows={2}
            className="field"
          />
        </Field>
      ))}
    </div>
  );
}

/** Page fill target and how bullets split across sections. */
function BulletBudget({ config, settings, onChange }: Omit<FormProps, "disabled">) {
  const fillValue = settings.fill_target ?? config?.fill_target ?? 0.93;
  return (
    <>
      <Field
        label={`Page fill target (${Math.round(fillValue * 100)}%)`}
        help="Grow when measured fill is below this. Lower = sparser page, fewer rewrites."
      >
        <input
          type="range"
          min={80}
          max={98}
          step={1}
          value={Math.round(fillValue * 100)}
          onChange={(e) => onChange({ ...settings, fill_target: Number(e.target.value) / 100 })}
          className={SLIDER}
        />
      </Field>
      <SectionBalance settings={settings} onChange={onChange} />
    </>
  );
}

const STAGE_TOGGLES: {
  key: "merge" | "suggest_vocabulary";
  label: string;
  help: string;
}[] = [
  {
    key: "merge",
    label: "Merge redundant bullets",
    help: "Only after a measured page overflow; the first thing tried before shortening or dropping bullets.",
  },
  {
    key: "suggest_vocabulary",
    label: "Suggest vocabulary from this run",
    help: "One extra call after a successful run: drafts spelling and opening-verb suggestions from this posting's own keyword gaps for review on the Vocabulary page. Uses this run's own backend.",
  },
];

function StageToggles({ settings, set }: { settings: JobSettings; set: Setter }) {
  return (
    <>
      {STAGE_TOGGLES.map((toggle) => (
        <Toggle
          key={toggle.key}
          label={toggle.label}
          help={toggle.help}
          checked={settings[toggle.key]}
          onChange={(v) => set(toggle.key, v)}
        />
      ))}
    </>
  );
}
