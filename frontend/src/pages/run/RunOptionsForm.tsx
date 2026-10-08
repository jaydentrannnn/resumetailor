import { useEffect, useId, useState } from "react";
import type { AppConfig, JobSettings } from "../../api";
import { Field, Toggle } from "../../components/Field";
import { IncludePanel } from "../../components/IncludePanel";
import { StylePromptField } from "../../components/StylePromptField";
import { DEFAULT_SETTINGS } from "../../state/runDefaults";

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
      <fieldset disabled={disabled} className="grid grid-cols-1 gap-4 sm:grid-cols-3">
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
            label="Cover letter"
            help="Also write a cover letter from the tailored resume."
            checked={settings.cover_letter}
            onChange={(v) => set("cover_letter", v)}
          />
        </div>
        {settings.cover_letter && (
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

  function resetDefaults() {
    // The model choice belongs to Settings, so a reset here keeps it.
    onChange({
      ...DEFAULT_SETTINGS,
      model: settings.model,
      model_name: settings.model_name,
      effort: settings.effort,
      apply: settings.apply,
      pages: config?.pages ?? DEFAULT_SETTINGS.pages,
      experience: config?.experience ?? 3,
      projects: config?.projects ?? 2,
    });
  }

  const fillValue = settings.fill_target ?? config?.fill_target ?? 0.93;
  const initialShareValue = settings.initial_bullet_share ?? config?.initial_bullet_share ?? 1;
  const experienceShareValue =
    settings.experience_bullet_share ?? config?.experience_bullet_share ?? 0.65;
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
      {coverOn && (
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
      )}
      <Field
        label={`Page fill target (${Math.round(fillValue * 100)}%)`}
        help="Grow when measured fill is below this. Lower = sparser page, fewer rewrites."
      >
        <input
          type="range"
          min={80}
          max={95}
          step={1}
          value={Math.round(fillValue * 100)}
          onChange={(e) => set("fill_target", Number(e.target.value) / 100)}
          className={SLIDER}
        />
      </Field>
      <Field
        label={`First-draft bullets (${Math.round(initialShareValue * 100)}%)`}
        help="Cap the opening selection to this share of available bullets. Lower starts sparser — but the page fill target above may still grow it back, so lower both to end sparser."
      >
        <input
          type="range"
          min={30}
          max={100}
          step={5}
          value={Math.round(initialShareValue * 100)}
          onChange={(e) => set("initial_bullet_share", Number(e.target.value) / 100)}
          className={SLIDER}
        />
      </Field>
      <Toggle
        label="Weight bullets toward experience"
        help="Budget experience and projects separately instead of one shared pool, where a keyword-dense project can otherwise out-rank every job."
        checked={settings.experience_bullet_share !== null}
        onChange={(v) => set("experience_bullet_share", v ? 0.65 : null)}
      />
      {settings.experience_bullet_share !== null && (
        <Field
          label={`${Math.round(experienceShareValue * 100)}% experience / ${100 - Math.round(experienceShareValue * 100)}% projects`}
        >
          <input
            type="range"
            min={0}
            max={100}
            step={5}
            value={Math.round(experienceShareValue * 100)}
            onChange={(e) => set("experience_bullet_share", Number(e.target.value) / 100)}
            className={SLIDER}
          />
        </Field>
      )}
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
      <StyleRules config={config} settings={settings} set={set} />
      <button
        type="button"
        onClick={resetDefaults}
        className="text-xs text-ink-muted underline-offset-2 hover:text-ink hover:underline"
      >
        Reset options to defaults
      </button>
    </fieldset>
  );
}

type Setter = <K extends keyof JobSettings>(key: K, value: JobSettings[K]) => void;

const STAGE_TOGGLES: {
  key: "merge" | "no_cache" | "no_expand" | "no_skills" | "no_facets" | "suggest_vocabulary";
  label: string;
  help: string;
}[] = [
  {
    key: "merge",
    label: "Merge redundant bullets",
    help: "Only after a measured page overflow; the first thing tried before shortening or dropping bullets.",
  },
  {
    key: "no_cache",
    label: "Force fresh results",
    help: "Ask the AI again instead of reusing saved results for this posting. Slower, and costs more on paid models.",
  },
  {
    key: "no_expand",
    label: "Skip experience expansion",
    help: "Do not generate application-form paste text after a successful fit.",
  },
  {
    key: "no_skills",
    label: "Skip skills list",
    help: "Do not generate the tailored skills list for application-form Skills fields.",
  },
  {
    key: "no_facets",
    label: "Skip tech / coursework selection",
    help: "Do not ask the model which project tags and courses to show; truncate pools in listed order to fit the line budgets.",
  },
  {
    key: "suggest_vocabulary",
    label: "Suggest vocabulary from this run",
    help: "One extra call after a successful run: drafts tag-alias/verb suggestions from this posting's own keyword gaps for review on the Settings tab. Uses this run's own backend.",
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

type StyleKey = "rewrite_style" | "expand_style" | "cover_style";

/** The three per-stage writing style blocks, each over its locked core rules. */
function StyleRules({
  config,
  settings,
  set,
}: {
  config: AppConfig | null;
  settings: JobSettings;
  set: Setter;
}) {
  /** Store an override only when it differs from the shipped default. */
  function setStyle(key: StyleKey, text: string | null, defaultText: string | undefined) {
    if (text === null) {
      set(key, null);
      return;
    }
    const trimmed = text.trim();
    set(key, !trimmed || trimmed === defaultText?.trim() ? null : text);
  }

  const blocks: { key: StyleKey; label: string; help: string; def?: string; core?: string }[] = [
    {
      key: "rewrite_style",
      label: "Resume bullet style",
      help: "Voice and emphasis for this profile. Length limits are enforced; field guidance prioritizes accurate verbs over forced variety.",
      def: config?.rewrite_style_default,
      core: config?.rewrite_core_rules,
    },
    {
      key: "expand_style",
      label: "Application-form expansion style",
      help: "Voice rules for the longer experience descriptions pasted into application forms.",
      def: config?.expand_style_default,
      core: config?.expand_core_rules,
    },
    {
      key: "cover_style",
      label: "Cover letter style",
      help: "Voice and structure rules for the cover letter body paragraphs.",
      def: config?.cover_style_default,
      core: config?.cover_core_rules,
    },
  ];

  return (
    <details className="border-y border-line py-3">
      <summary className="cursor-pointer text-sm font-medium text-ink">Writing style rules</summary>
      <div className="mt-3 space-y-4">
        {blocks.map((block) => (
          <StylePromptField
            key={block.key}
            label={block.label}
            help={block.help}
            value={settings[block.key]}
            defaultText={block.def ?? ""}
            lockedCoreRules={block.core ?? ""}
            onChange={(text) => setStyle(block.key, text, block.def)}
          />
        ))}
      </div>
    </details>
  );
}
