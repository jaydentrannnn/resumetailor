"""The stage replays: each takes a `Case`, calls the real pipeline function, and returns
a JSON-ready dict of outputs plus `metrics`. Run inside `arms.run`, which pins the arm's
model and effort and records telemetry around every call."""

from __future__ import annotations

from typing import Any

from resume_tailor import config, workspace
from resume_tailor.content import bullet_tags, data, industries, style
from resume_tailor.pipeline import expand, fit_types, jd, rewrite, tag_infer
from resume_tailor.pipeline.jd import JobRequirements

from . import corpus, hybrid_extract, judge, metrics
from .corpus import Case

#: A case needs this many of its saved bullet ids still in today's resume.
MIN_BULLETS = 3


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
        self.light_spec = self.settings.ai_models.light.spec("light")
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
        outcome = rewrite.rewrite_bullets(sources, requirements, char_budget=self.budget,
                                          repair_widows=False, repair_verbs=False)
        return self._rewrite_record(case, outcome.texts, outcome.fabrications_rejected, 0)

    def polish(self, case: Case, draft: dict[str, Any], effort: str) -> dict[str, Any]:
        """`rewrite.cosmetic_polish` on one case's frozen `draft` record at `effort`;
        "none" keeps the drafts as they are and makes no call."""
        texts, revoiced = dict(draft["texts"]), 0
        if effort != "none":
            by_id = {b.id: b for b in self.sources(case)}
            texts, _, revoiced, _ = rewrite.cosmetic_polish(
                texts, by_id, self._requirements(case), repair_verbs=True, effort=effort)
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

    def judge_inputs(self, stage: str, case: Case, a: dict, b: dict) -> tuple:
        """`(build, output a, output b)` for `judge.both_orders` from two arm results."""
        if stage == "extract":
            return judge.extract_prompt(case.jd_text), a["requirements"], b["requirements"]
        requirements = self._requirements(case)
        must = [k.phrase for k in requirements.keywords if k.importance == "must_have"]
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
