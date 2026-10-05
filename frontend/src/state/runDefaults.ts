/** Default run settings: the starting point for a fresh Tailor session and the merge
 * base for settings loaded from the server. */

import type { IncludeOptions, JobSettings } from "../api";

/** All-included defaults for a fresh `IncludeOptions` — the merge base whenever a
 * settings.json predates this field or a fresh session needs a starting point. */
export const DEFAULT_INCLUDE: IncludeOptions = {
  contact_fields: null,
  gpa: true,
  coursework: true,
  exclude_entries: [],
  exclude_sections: [],
  exclude_experience: [],
  exclude_projects: [],
  section_order: null,
};

/** Defaults for a fresh Tailor session; also the merge base for settings from the server. */
export const DEFAULT_SETTINGS: JobSettings = {
  pages: 1,
  experience: null,
  projects: null,
  // Ollama, not Claude: a fresh install should run without an Anthropic key. Keep this in
  // step with `JobSettings.model`'s server-side default — the seeding branch below reads
  // this value rather than repeating the name.
  model: "ollama",
  /** null keeps the server's OLLAMA_MODEL (gemma4:cloud); only a typed value overrides. */
  ollama_model: null,
  /** null keeps the server's GEMINI_MODEL; only a typed value overrides. */
  gemini_model: null,
  rewrite_model: null,
  expand_model: null,
  skills_model: null,
  cover_model: null,
  review_model: null,
  answer_model: null,
  effort: null,
  no_semantic: false,
  no_widow_repair: false,
  no_verb_repair: false,
  merge: true,
  no_cache: false,
  // Matches `config.EXTRACT_CONSENSUS_RUNS` server-side. No UI control exposes this;
  // it exists here only so "Reset to defaults" round-trips it instead of dropping it.
  extract_runs: 0, // 0 = automatic: 1 vote on Anthropic/Gemini, 3 on local models
  max_concurrent_jobs: 2,
  no_expand: true,
  no_skills: false,
  cover_letter: false,
  no_cover_letter: false,
  cover_angles: {
    why_company: "",
    problem: "",
    approach: "",
    tone: "",
  },
  no_facets: false,
  no_project_links: false,
  fill_target: null,
  initial_bullet_share: null,
  experience_bullet_share: null,
  max_bullets_per_entry: null,
  include: DEFAULT_INCLUDE,
  suggest_vocabulary: false,
  rewrite_style: null,
  expand_style: null,
  cover_style: null,
  model_name: null,
  apply: {
    enabled: false,
    schedule_time: "02:00",
    readme_url:
      "https://raw.githubusercontent.com/SimplifyJobs/Summer2027-Internships/dev/README.md",
    categories: [
      "Software Engineering Internship Roles",
      "Data Science, AI & Machine Learning Internship Roles",
    ],
    sources: [
      {
        id: "simplify-internships",
        kind: "simplify_html",
        url: "https://raw.githubusercontent.com/SimplifyJobs/Summer2027-Internships/dev/README.md",
        categories: [
          "Software Engineering Internship Roles",
          "Data Science, AI & Machine Learning Internship Roles",
        ],
        enabled: true,
      },
      {
        id: "simplify-newgrad",
        kind: "simplify_html",
        url: "https://raw.githubusercontent.com/SimplifyJobs/New-Grad-Positions/dev/README.md",
        categories: [
          "Software Engineering New Grad Roles",
          "Data Science, AI & Machine Learning New Grad Roles",
        ],
        enabled: true,
      },
      {
        id: "speedyapply",
        kind: "pipe_table",
        url: "https://raw.githubusercontent.com/speedyapply/2027-SWE-College-Jobs/main/README.md",
        categories: ["2027 USA SWE Internships", "USA Positions"],
        enabled: true,
      },
    ],
    max_age_days: 1,
    exclude_advanced_degree: true,
    exclude_citizenship_required: true,
    exclude_no_sponsorship: false,
    max_new_per_day: 40,
    screen: {
      allowed_seniority: ["intern", "entry"],
      block_patterns: ["\\bU\\.?S\\.? citizen", "security clearance"],
    },
    eligibility: {
      hard_reject_years: 4,
      flag_years: 2,
      extra_title_block: [],
      extra_text_block: [],
    },
    auto_submit_ats: [],
    auto_submit_max_per_run: 0,
    max_parallel_fills: 2,
    auto_submit_max_per_day: 25,
    auto_submit_max_per_company_per_day: 2,
    auto_submit_enabled: false,
    blocker_mode: "continue",
    reuse_threshold: 0.72,
    cover_letter: true,
    model_provider: "ollama",
    model_name: "nemotron-3-super:cloud",
  },
};
