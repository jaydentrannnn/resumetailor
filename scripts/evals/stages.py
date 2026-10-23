"""The stage replays: each takes a `Case`, calls the real pipeline function, and returns
a JSON-ready dict of outputs plus `metrics`. Run inside `arms.run`, which pins the arm's
model and effort and records telemetry around every call."""

from __future__ import annotations

import json
import os
from typing import Any

from resume_tailor import config, workspace
from resume_tailor.content import bullet_tags, data, industries, style
from resume_tailor.pipeline import (
    bullet_checks,
    coverletter,
    coverletter_format,
    expand,
    fit_types,
    followups,
    jd,
    review,
    rewrite,
    tag_infer,
)
from resume_tailor.pipeline.jd import JobRequirements

from . import corpus, hybrid_extract, judge, metrics, review_scope, variants
from .corpus import Case

#: A case needs this many of its saved bullet ids still in today's resume.
MIN_BULLETS = 3
#: Unmet must-haves the gap-bridge arm offers the cover letter (experiment 4d).
MAX_GAPS = 2
#: A model spec (string, or a JSON object) that replaces the profile's Light model for
#: every arm; the profile's own model still judges (`profile_spec`).
LIGHT_ENV = "EVAL_LIGHT"


def light_override() -> config.ModelSpec | None:
    raw = os.environ.get(LIGHT_ENV, "").strip()
    if not raw:
        return None
    return json.loads(raw) if raw.startswith("{") else raw


def cosmetic_polish(texts: dict[str, str], by_id: dict, requirements: JobRequirements, *,
                    effort: str | None = None) -> tuple[dict[str, str], int]:
    """The opening-verb and phrase-repeat repair production ran after drafting until
    2026-10-16, removed because it measured worse than none on every model tested. Kept
    here, eval-only, so the frozen-draft experiments can be rerun. Returns
    `(texts, verbs diversified)`."""
    phrase_overuse = bullet_checks.phrase_collisions(
        texts, [kw.phrase for kw in requirements.keywords], by_id,
        pages=config.DEFAULT_PAGE_TARGET,
        repairable=set(texts) - set(bullet_checks.verb_collisions(texts)),
    )
    polished, _, revoiced, _ = followups._polish(
        texts, by_id, requirements, repair_widows=False, repair_verbs=True,
        phrase_overuse=phrase_overuse, **({"effort": effort} if effort else {}),
    )
    return {bid: polished[bid] for bid in texts}, revoiced


def _role(entry) -> str:
    """The entry heading a bullet sits under: "Title at Company", or a project's name."""
    if hasattr(entry, "company"):
        return f"{entry.title} at {entry.company}"
    return getattr(entry, "name", "")


class Replay:
    """One profile's resume, styles and guidance, shared by every case of a batch.

    Match tags are inferred once here and re-installed in each task's run context
    (`setup`). A batch still covers exactly one workspace; build a new `Replay`
    (sequentially) for the next one.
    """

    def __init__(self, workspace_id: str = "default"):
        from resume_tailor.web.job_routing import tailoring_guidance
        from resume_tailor.web.schemas import JobSettings

        self.workspace_id = workspace_id
        workspace.bootstrap(workspace_id=workspace_id, migrate=False)
        self.settings = JobSettings.model_validate(workspace.load_settings()["defaults"])
        self.profile_spec = self.settings.ai_models.light.spec("light")
        self.light_spec = light_override() or self.profile_spec
        self.resume = data.load()
        # Skill inference is cached; a miss calls the model, so route it like a job would.
        with config.pinned("ollama", overrides=dict.fromkeys(config.PURPOSES, self.light_spec)):
            self.inference = tag_infer.prepare_run(self.resume)
        self.by_id = {b.id: b for b in self.resume.all_bullets()}
        self.role = {b.id: _role(e) for s in self.resume.entry_sections
                     for e in s.entries for b in e.bullets}
        self.known_tags = bullet_tags.known_terms(self.resume)
        # Fetched postings have no saved run: they get today's profile guidance.
        self.guidance = tailoring_guidance(self.settings, workspace_id, self.resume)
        self.budget = fit_types.default_bullet_char_budget()

    # -- per-task setup (runs inside the task's own config context) -------------------

    def setup(self, case: Case) -> None:
        # Each task runs in its own run context, which reads only its own match tags.
        bullet_tags.annotate(self.resume, self.inference.skills)
        saved = industries.load(case.job_dir) if case.job_dir is not None else None
        industries.bind(saved or self.guidance)
        style.activate(
            rewrite=self.settings.rewrite_style,
            expand=self.settings.expand_style,
            cover=self.settings.cover_style,
        )

    # -- eligibility --------------------------------------------------------------------

    def sources(self, case: Case) -> list:
        return [self.by_id[i] for i in case.bullet_ids if i in self.by_id]

    def can_rewrite(self, case: Case) -> bool:
        return case.requirements_json() is not None and len(self.sources(case)) >= MIN_BULLETS

    # -- stages -------------------------------------------------------------------------

    @staticmethod
    def _requirements(case: Case) -> JobRequirements:
        return JobRequirements.model_validate_json(case.requirements_json())

    def rewrite(self, case: Case) -> dict[str, Any]:
        """Rewrite the run's own bullets against its own saved extraction."""
        sources, requirements = self.sources(case), self._requirements(case)
        outcome = rewrite.rewrite_bullets(sources, requirements, char_budget=self.budget)
        return self._rewrite_record(case, outcome.texts, outcome.fabrications_rejected,
                                    outcome.verbs_diversified)

    def prepolish(self, case: Case) -> dict[str, Any]:
        """First drafts after the factual retry, before cosmetic polish: the frozen drafts
        every polish arm of experiment E1 starts from (persisted as the `draft` arm)."""
        sources, requirements = self.sources(case), self._requirements(case)
        outcome = rewrite.rewrite_bullets(sources, requirements, char_budget=self.budget)
        return self._rewrite_record(case, outcome.texts, outcome.fabrications_rejected, 0)

    def polish(self, case: Case, draft: dict[str, Any], effort: str) -> dict[str, Any]:
        """`cosmetic_polish` on one case's frozen `draft` record at `effort` (None: the
        stage's default); "none" keeps the drafts as they are and makes no call."""
        texts, revoiced = dict(draft["texts"]), 0
        if effort != "none":
            by_id = {b.id: b for b in self.sources(case)}
            texts, revoiced = cosmetic_polish(texts, by_id, self._requirements(case),
                                              effort=effort)
        return self._rewrite_record(case, texts, draft["fabrications_rejected"], revoiced)

    def _rewrite_record(self, case: Case, texts: dict[str, str],
                        rejected: dict[str, list[str]], revoiced: int) -> dict[str, Any]:
        sources, requirements = self.sources(case), self._requirements(case)
        final = {b.id: texts.get(b.id, b.text) for b in sources}
        return {
            "texts": texts,
            "fabrications_rejected": rejected,
            "verbs_diversified": revoiced,
            "must": metrics.must_sets(sources, final, requirements),
            "metrics": metrics.rewrite_metrics(sources, texts, rejected, requirements,
                                               self.budget),
        }

    def expand(self, case: Case) -> dict[str, Any]:
        """Expand the experience entries the run's resume used, cache bypassed."""
        expansion = expand.expand_experience(
            self.resume, self._requirements(case),
            resume_bullet_ids=set(case.bullet_ids), use_cache=False,
        )
        return {
            "entries": [
                {"entry_key": e.entry_key, "bullets": e.bullets, "warnings": e.warnings}
                for e in expansion.entries
            ],
            "warnings": expansion.warnings,
            "metrics": metrics.expand_metrics(expansion),
        }

    def extract(self, case: Case) -> dict[str, Any]:
        """Fresh extraction of the posting (current method), cache bypassed."""
        requirements = jd.extract(case.jd_text, known_tags=self.known_tags, use_cache=False)
        return self.extraction_record(case, requirements)

    def build_dictionary(self, saved: list[Case]) -> None:
        """The E dictionary: library + this resume's skills + every saved extraction,
        each tagged with its posting so `hybrid` can leave the posting's own out."""
        from resume_tailor.content import libraries

        effective = libraries.resolve_effective()
        self.dictionary = hybrid_extract.Dictionary(
            [*effective.terms, *self.known_tags], effective.tag_aliases)
        for case in saved:
            raw = case.requirements_json()
            if raw:
                self.dictionary.add_extraction(
                    corpus.digest(case.jd_text), JobRequirements.model_validate_json(raw))

    def hybrid(self, case: Case) -> dict[str, Any]:
        """Dictionary candidates + one labelling call (experiment E)."""
        requirements, found = hybrid_extract.extract(
            case.jd_text, self.dictionary, known_tags=self.known_tags,
            exclude=corpus.digest(case.jd_text),
        )
        record = self.extraction_record(case, requirements)
        record["metrics"]["candidates"] = found
        return record

    # -- cover letter and review (experiments 4d, 4e) ------------------------------------

    @staticmethod
    def tailored(case: Case) -> dict[str, str]:
        """The run's final tailored bullets (`bullets.json`), `{}` when absent."""
        return corpus._read_json(case.job_dir / "bullets.json") if case.job_dir else {}

    def can_cover(self, case: Case) -> bool:
        return case.requirements_json() is not None and len(self.tailored(case)) >= MIN_BULLETS

    def unmet(self, case: Case) -> list[str]:
        """Must-haves the resume does not have at all (coverage's `resume is None`) and
        never names in its text, in posting order, at most `MAX_GAPS`: the gaps the
        cover-letter arm may acknowledge."""
        if getattr(self, "_resume_text", None) is None:
            from resume_tailor.document import render

            self._resume_text = "\n".join(render.visible_text(
                self.resume, {b.id: b.text for b in self.resume.all_bullets()}))
        claimed = self._requirements(case).as_claimed()
        known = set(self.known_tags)
        phrases = {}
        for k in claimed.by_importance("must_have"):
            if k.canonical not in known and not bullet_checks.contains_phrase(
                    self._resume_text, k.phrase):
                phrases.setdefault(k.canonical, k.phrase)
        return list(phrases.values())[:MAX_GAPS]

    def _cover(self, case: Case) -> dict[str, Any]:
        letter = coverletter.draft_letter(
            self.resume, self._requirements(case), self.tailored(case), case.jd_text,
            use_cache=False,
        )
        unmet = self.unmet(case)
        return {
            "paragraphs": letter.paragraphs, "warnings": letter.warnings, "unmet": unmet,
            "metrics": metrics.cover_metrics(letter.paragraphs, letter.warnings,
                                             letter.word_count, unmet),
        }

    def cover(self, case: Case) -> dict[str, Any]:
        """The current cover letter for the run's own tailored bullets, cache bypassed."""
        return self._cover(case)

    def cover_gaps(self, case: Case) -> dict[str, Any]:
        """The same letter with the run's unmet must-haves offered as gaps to bridge."""
        with variants.gaps(self.unmet(case)):
            return self._cover(case)

    # -- company facts in the cover letter (L4.6) -------------------------------------

    #: Facts per case id, researched once before the arms run (`research_company`).
    frozen_facts: dict[str, list[str]] = {}

    @staticmethod
    def company_name(case: Case) -> str:
        packet = corpus._read_json(case.job_dir / "packet.json") if case.job_dir else {}
        return str(packet.get("company") or "").strip()

    def research_company(self, case: Case) -> dict[str, Any]:
        """Research the case's company once, through the store: the posting, plus the
        `<name>.com` homepage when it names the company (no search key is assumed)."""
        from resume_tailor.infra import polite_fetch
        from resume_tailor.research import company_run

        name = self.company_name(case)
        with polite_fetch.Fetcher() as fetcher:
            site = _guess_site(name, fetcher)
            research = company_run.run(company=name, jd_text=case.jd_text, site_url=site,
                                       fetcher=fetcher)
        return {"company": name, "site": site, "facts": [f.text for f in research.facts],
                "dropped": research.dropped,
                "sources": [[s.kind, s.url or ""] for s in research.sources]}

    def cover_company(self, case: Case) -> dict[str, Any]:
        """The current letter with the case's frozen company facts offered."""
        facts = self.frozen_facts.get(case.case_id, [])
        with variants.company(facts):
            record = self._cover(case)
        return {**record, "facts": facts}

    def review(self, case: Case) -> dict[str, Any]:
        """The current hiring-manager review of the run's tailored bullets."""
        result = review.review_bullets(self.resume, self._requirements(case), self.tailored(case))
        record = {
            "scope_read": result.scope_read, "consistency": [],
            "bullets": [{"id": b.id, "verdict": b.verdict, "reason": b.reason,
                         "replacement": b.replacement, "dropped_note": b.dropped_note,
                         "offered": b.verdict == "rewrite"
                         and bool(b.replacement or b.dropped_note),
                         "scope_risk": "stretch" if b.scope_note else "none",
                         "scope_note": b.scope_note}
                        for b in result.bullets],
        }
        return {**record, "metrics": metrics.review_metrics(record)}

    def review_scope(self, case: Case) -> dict[str, Any]:
        """The broader review: scope risk, softer wording, consistency (experiment 4e)."""
        cover = corpus._read_json(case.job_dir / "cover.json") if case.job_dir else {}
        record = review_scope.review_scoped(self.resume, self._requirements(case),
                                            self.tailored(case), cover.get("paragraphs") or ())
        return {**record, "metrics": metrics.review_metrics(record)}

    def review_note(self, case: Case) -> dict[str, Any]:
        """Variant B: the current review plus a stretch flag and note, nothing else."""
        record = review_scope.review_scoped(self.resume, self._requirements(case),
                                            self.tailored(case), variant="note")
        return {**record, "metrics": metrics.review_metrics(record)}

    def judge_inputs(self, stage: str, case: Case, a: dict, b: dict) -> tuple:
        """`(build, output a, output b)` for `judge.both_orders` from two arm results."""
        if stage == "extract":
            return judge.extract_prompt(case.jd_text), a["requirements"], b["requirements"]
        requirements = self._requirements(case)
        must = [k.phrase for k in requirements.keywords if k.importance == "must_have"]
        if stage in ("cover", "cover-company"):
            shown = coverletter_format._format_tailored_entries(self.resume, self.tailored(case))
            facts = self.frozen_facts.get(case.case_id, []) if stage == "cover-company" else []
            return (judge.cover_prompt(requirements.title, must, shown, facts),
                    a["paragraphs"], b["paragraphs"])
        if stage in ("review", "review-note"):
            return judge.review_prompt(requirements.title, must, self.tailored(case)), a, b
        if stage == "rewrite":
            return judge.rewrite_prompt(requirements.title, must, self.judge_sources(
                [i for i in a["texts"] if i in self.by_id])), a["texts"], b["texts"]
        # Expansion reads every bullet of each entry it expands, not only the selected ones.
        entries = {expand.entry_key(e.id): {
            "role": _role(e),
            "sources": [judge.source(x.text, _role(e), x.tags) for x in e.bullets],
        } for e in self.resume.experience}
        return judge.expand_prompt(requirements.title, must, entries), a["entries"], b["entries"]

    def judge_sources(self, ids: list[str]) -> dict[str, dict]:
        """`{bullet id: judge.source(...)}`: each bullet with the role and permitted skills
        the rewrite model was shown."""
        return {i: judge.source(self.by_id[i].text, self.role.get(i, ""), self.by_id[i].tags)
                for i in ids}

    def extraction_record(self, case: Case, requirements: JobRequirements) -> dict[str, Any]:
        return {
            "requirements": requirements.model_dump(mode="json"),
            "metrics": metrics.extract_metrics(requirements, case.jd_text, self.resume),
        }


def _guess_site(company: str, fetcher) -> str:
    """``https://www.<name>.com/`` when its page names the company, else "" (eval only:
    production takes the site from search or the student)."""
    from resume_tailor.apply.discovery import identity
    from resume_tailor.infra.polite_fetch import FetchError
    from resume_tailor.research import company_sources, pages

    full, plain = company_sources._squashed(company)
    words = identity.normalize_company(company).split()
    if not (plain or full) or not words:
        return ""
    url = f"https://www.{plain or full}.com/"
    try:
        text, title, _ = pages.page_text(fetcher.get(url))
    except FetchError:
        return ""
    return url if words[0] in f"{title} {text[:2000]}".casefold() else ""
