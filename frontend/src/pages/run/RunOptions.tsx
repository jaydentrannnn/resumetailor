import { useEffect, useId, useState } from "react";
import { Link } from "react-router-dom";
import type { AppConfig, JobSettings } from "../../api";
import { Field, Toggle } from "../../components/Field";
import { IncludePanel } from "../../components/IncludePanel";
import { StylePromptField } from "../../components/StylePromptField";
import { profileDefaultModel } from "../../lib/modelLabel";
import { providerInfo } from "../../lib/providers";
import { DEFAULT_SETTINGS } from "../../state/runDefaults";

const OPEN_KEY = "rt.runOptions.open.";

function readOpen(workspaceId: string): boolean {
  try {
    return window.localStorage.getItem(OPEN_KEY + workspaceId) === "1";
  } catch {
    return false;
  }
}

/**
 * Run options, simple first: page count and the cover letter are always visible;
 * everything else sits under "More options", whose open state is remembered per
 * profile. The AI model is chosen in Settings; this card only names it.
 */
export function RunOptions({
  config,
  settings,
  onChange,
  disabled,
  workspaceId,
  saveNotice,
}: {
  config: AppConfig | null;
  settings: JobSettings;
  onChange: (s: JobSettings) => void;
  disabled: boolean;
  workspaceId: string;
  saveNotice: React.ReactNode;
}) {
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

  /** Parse a number-input's raw string, clamped to [min, max]. Returns `undefined`
   * for an empty or unparseable value so the caller can skip the write entirely —
   * `Number("")` is `0`, which would otherwise silently persist and 422 on save. */
  function parseClamped(raw: string, min: number, max: number): number | undefined {
    if (raw.trim() === "") return undefined;
    const n = Number(raw);
    if (!Number.isFinite(n)) return undefined;
    return Math.min(max, Math.max(min, Math.round(n)));
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
  const provider = providerInfo(settings.model)?.name ?? settings.model;
  const modelName = settings.model_name || profileDefaultModel(settings, config);

  return (
    <section className="rounded-xl border border-line bg-panel p-5 shadow-sm lg:col-span-2 lg:row-start-1">
      <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
        <h2 className="font-display text-xl font-semibold">Options</h2>
        <p className="text-sm text-ink-muted">
          Using <strong className="font-medium text-ink">{provider}</strong>
          {modelName && !modelName.startsWith("e.g.") ? ` · ${modelName}` : ""}{" "}
          <Link
            to="/settings?tab=models"
            className="font-semibold text-accent underline-offset-2 hover:underline"
          >
            Change
          </Link>
        </p>
      </div>
      {saveNotice}
      <fieldset disabled={disabled} className="mt-4 grid grid-cols-1 gap-4 sm:grid-cols-3">
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

      <div className="mt-4 border-t border-line pt-3">
        <button
          type="button"
          onClick={() => setOpen((o) => !o)}
          aria-expanded={open}
          aria-controls={moreId}
          className="text-sm font-semibold text-ink hover:text-accent"
        >
          More options {open ? "▾" : "▸"}
        </button>
        {open && (
          <div id={moreId} className="mt-4 grid gap-6 lg:grid-cols-2">
            <fieldset disabled={disabled} className="space-y-3">
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
                <div className="space-y-3 rounded-md border border-line/80 bg-paper/40 p-3">
                  <p className="text-xs text-ink-muted">
                    Optional cover letter angles for this application. Leave blank for the default
                    letter.
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
                  className="w-full accent-[var(--color-accent)]"
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
                  className="w-full accent-[var(--color-accent)]"
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
                    className="w-full accent-[var(--color-accent)]"
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
                    set(
                      "max_bullets_per_entry",
                      e.target.value === "" ? null : Number(e.target.value),
                    )
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
              <Toggle
                label="Merge redundant bullets"
                help="Only after a measured page overflow; the first thing tried before shortening or dropping bullets."
                checked={settings.merge}
                onChange={(v) => set("merge", v)}
              />
              <Toggle
                label="Force fresh results"
                help="Ask the AI again instead of reusing saved results for this posting. Slower, and costs more on paid models."
                checked={settings.no_cache}
                onChange={(v) => set("no_cache", v)}
              />
              <Toggle
                label="Skip experience expansion"
                help="Do not generate application-form paste text after a successful fit."
                checked={settings.no_expand}
                onChange={(v) => set("no_expand", v)}
              />
              <Toggle
                label="Skip skills list"
                help="Do not generate the tailored skills list for application-form Skills fields."
                checked={settings.no_skills}
                onChange={(v) => set("no_skills", v)}
              />
              <Toggle
                label="Skip tech / coursework selection"
                help="Do not ask the model which project tags and courses to show; truncate pools in listed order to fit the line budgets."
                checked={settings.no_facets}
                onChange={(v) => set("no_facets", v)}
              />
              <Toggle
                label="Suggest vocabulary from this run"
                help="One extra call after a successful run: drafts tag-alias/verb suggestions from this posting's own keyword gaps for review on the Settings tab. Uses this run's own backend."
                checked={settings.suggest_vocabulary}
                onChange={(v) => set("suggest_vocabulary", v)}
              />
              <details className="rounded-md border border-line/80 bg-paper/40 px-3 py-2">
                <summary className="cursor-pointer text-sm font-medium text-ink">
                  Writing style rules
                </summary>
                <div className="mt-3 space-y-3">
                  <StylePromptField
                    label="Resume bullet style"
                    help="Voice and emphasis for this profile. Length limits are enforced; field guidance prioritizes accurate verbs over forced variety."
                    value={settings.rewrite_style}
                    defaultText={config?.rewrite_style_default ?? ""}
                    lockedCoreRules={config?.rewrite_core_rules ?? ""}
                    onChange={(text) => {
                      if (text === null) {
                        set("rewrite_style", null);
                        return;
                      }
                      const trimmed = text.trim();
                      if (!trimmed || trimmed === config?.rewrite_style_default?.trim()) {
                        set("rewrite_style", null);
                      } else {
                        set("rewrite_style", text);
                      }
                    }}
                  />
                  <StylePromptField
                    label="Application-form expansion style"
                    help="Voice rules for the longer experience descriptions pasted into application forms."
                    value={settings.expand_style}
                    defaultText={config?.expand_style_default ?? ""}
                    lockedCoreRules={config?.expand_core_rules ?? ""}
                    onChange={(text) => {
                      if (text === null) {
                        set("expand_style", null);
                        return;
                      }
                      const trimmed = text.trim();
                      if (!trimmed || trimmed === config?.expand_style_default?.trim()) {
                        set("expand_style", null);
                      } else {
                        set("expand_style", text);
                      }
                    }}
                  />
                  <StylePromptField
                    label="Cover letter style"
                    help="Voice and structure rules for the cover letter body paragraphs."
                    value={settings.cover_style}
                    defaultText={config?.cover_style_default ?? ""}
                    lockedCoreRules={config?.cover_core_rules ?? ""}
                    onChange={(text) => {
                      if (text === null) {
                        set("cover_style", null);
                        return;
                      }
                      const trimmed = text.trim();
                      if (!trimmed || trimmed === config?.cover_style_default?.trim()) {
                        set("cover_style", null);
                      } else {
                        set("cover_style", text);
                      }
                    }}
                  />
                </div>
              </details>
              <button
                type="button"
                onClick={resetDefaults}
                className="text-xs text-ink-muted underline-offset-2 hover:text-accent hover:underline"
              >
                Reset options to defaults
              </button>
            </fieldset>
            <fieldset disabled={disabled} className="contents">
              <IncludePanel settings={settings} onChange={onChange} />
            </fieldset>
          </div>
        )}
      </div>
    </section>
  );
}
