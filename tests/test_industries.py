"""Profile selection, prompt boundaries, cache separation, and reproducible runs."""

from __future__ import annotations

import json
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from resume_tailor import (
    config,
    coverletter,
    expand,
    facets,
    industries,
    jd,
    libraries,
    llm,
    rewrite,
    skills,
    style,
    workspace,
)
from resume_tailor.data import Bullet
from resume_tailor.web.app import app
from resume_tailor.web.jobs import JobQueue, regenerate_cover_letter
from resume_tailor.web.schemas import JobSettings
from tests.fixtures import synthetic_resume


@pytest.fixture
def profile(tmp_path, monkeypatch):
    paths = {**config.default_context().paths,
             "SETTINGS_PATH": tmp_path / "settings.json",
             "OUTPUT_DIR": tmp_path / "output", "CACHE_DIR": tmp_path / "cache",
             "MASTER_RESUME_PATH": tmp_path / "resume.json"}
    paths["MASTER_RESUME_PATH"].write_text(synthetic_resume().model_dump_json(), "utf-8")
    with config.use_context(replace(config.default_context(), paths=paths, guidance=None)):
        yield tmp_path


def capture(target="finance-consulting", **overrides):
    return industries.capture(
        target, {stage: overrides.get(stage) for stage in ("rewrite", "expand", "cover")},
        resume=synthetic_resume(),
    )


def test_legacy_prompts_and_custom_override_are_preserved(profile):
    assert industries.capture(None, {}) is None
    assert rewrite._system() == rewrite._SYSTEM
    assert expand._system() == expand._SYSTEM
    assert coverletter._system() == coverletter._SYSTEM
    custom = "Prefer short concrete descriptions."
    with config.use_context(config.default_context()):
        snapshot = capture(rewrite=custom)
        industries.bind(snapshot)
        style.activate(**snapshot.styles)
        assert style.active("rewrite") == custom
        assert "NEVER introduce a skill" in rewrite._system()
        assert "Candidate claims must come" in rewrite._system()
        assert "Profile target field: Finance & Consulting" in rewrite._system()
        style.activate()
        # Clearing an override restores this profile's field default.
        assert "financial modeling" in style.active("rewrite")


def test_settings_field_survives_old_clients_and_invalid_ids_are_rejected(profile):
    workspace.save_settings({"rewrite_style": "My custom style."})
    with TestClient(app) as client:
        assert client.get("/api/settings").json()["target_field"] is None
        result = client.put("/api/settings/target-field", json={
            "target_field": "finance-consulting"
        })
        assert result.status_code == 200
        body = result.json()
        assert len(body["target_fields"]) == 6
        assert "finance-consulting" in body["effective_vocabulary_packs"]
        assert "financial modeling" in body["rewrite_style_default"]
        assert "or the job posting" not in body["cover_core_rules"]
        assert client.get("/api/settings").json()["settings"]["rewrite_style"] == "My custom style."
        # An older save that knows only run settings must not clear profile metadata.
        assert client.put("/api/settings", json={"settings": {"pages": 2}}).status_code == 200
        assert client.get("/api/settings").json()["target_field"] == "finance-consulting"
        assert client.put("/api/settings/target-field", json={
            "target_field": "unknown"
        }).status_code == 422
        assert client.put("/api/settings", json={
            "settings": {}, "target_field": "marketing"
        }).status_code == 200
        assert client.get("/api/settings").json()["target_field"] == "marketing"
        assert client.put("/api/settings/target-field", json={"target_field": None}).status_code == 200
        assert client.get("/api/config").json()["rewrite_style_default"] == style.DEFAULT_REWRITE_STYLE.strip()


def test_pack_composition_preserves_files_custom_overrides_and_source_limits(profile):
    state = libraries.WorkspaceLibraryState(
        enabled_packs=["core-tech", "marketing"],
        overrides=libraries.LibraryOverrides(tag_aliases={"dcf": "custom valuation"}),
    )
    libraries.write_workspace_state(state)
    before = libraries.workspace_file().read_bytes()
    snapshot = capture()
    assert snapshot.tag_aliases["dcf"] == "custom valuation"
    assert "marketing" in snapshot.packs
    assert libraries.workspace_file().read_bytes() == before
    industries.bind(snapshot)
    source = Bullet(id="excel", text="Analyzed records using Excel.", tags=["excel"])
    assert rewrite.check_fabrication(source, "Analyzed records using Bloomberg.")
    assert "matching aids" in rewrite._system()
    assert "proficiency" in rewrite._system()


def test_cache_fingerprints_change_with_guidance_and_custom_styles(profile):
    snapshots = [capture("general"), capture(), capture(cover="Use short paragraphs.")]
    fingerprints = {}
    for snapshot in snapshots:
        industries.bind(snapshot)
        config.resolve("ollama")
        fingerprints[snapshot.fingerprint()] = [config.fingerprint(stage) for stage in industries.STAGES]
    for index in range(len(industries.STAGES)):
        assert len({values[index] for values in fingerprints.values()}) == 3


def test_run_snapshot_survives_profile_and_catalog_edits(profile, monkeypatch):
    workspace.save_settings({}, target_field="finance-consulting")
    queue = JobQueue()
    monkeypatch.setattr(queue, "_ensure_worker", lambda: None)
    job, _ = queue.submit("FP&A analyst posting", JobSettings())
    old_system = job.guidance.systems["cover"]
    workspace.save_settings({}, target_field="marketing")
    altered = {**industries.catalog()["finance-consulting"], "priorities": "Changed guidance."}
    monkeypatch.setitem(industries.catalog(), "finance-consulting", altered)
    observed = []
    monkeypatch.setattr(queue, "_execute_in_context", lambda _job: observed.append(
        (industries.active().target_field, coverletter._system())
    ))
    queue._execute(job)
    assert observed == [("finance-consulting", old_system)]
    industries.save(job.guidance, profile)
    loaded = industries.load(profile)
    assert loaded.fingerprint() == job.guidance.fingerprint()
    assert loaded.systems["cover"] == old_system


def test_cover_regeneration_uses_saved_prompts_and_vocabulary(profile, monkeypatch):
    snapshot = capture(cover="Use direct sentences.")
    directory = config.OUTPUT_DIR / "jobs" / "saved"
    directory.mkdir(parents=True)
    industries.save(snapshot, directory)
    resume = synthetic_resume()
    (directory / "bullets.json").write_text(json.dumps({
        bullet.id: bullet.text for bullet in resume.all_bullets()
    }), "utf-8")
    requirements = jd.JobRequirements(title="Analyst", seniority="entry")
    (directory / "requirements.json").write_text(requirements.model_dump_json(), "utf-8")
    (directory / "jd.txt").write_text("Analyst at Example Company", "utf-8")
    config.resolve("ollama")
    (directory / "backends.json").write_text(json.dumps(config.backend_specs_snapshot()), "utf-8")
    workspace.save_settings({}, target_field="marketing")
    seen = []

    def draft(*args, **kwargs):
        seen.append((industries.active().target_field, coverletter._system(), style.active("cover")))
        return coverletter.CoverLetter(paragraphs=["A saved example."], model="stub")

    monkeypatch.setattr(coverletter, "draft_letter", draft)
    monkeypatch.setattr(coverletter, "render_cover_letter", lambda *args, **kwargs: None)
    regenerate_cover_letter("saved")
    assert seen == [("finance-consulting", snapshot.systems["cover"], "Use direct sentences.")]
    assert industries.active() is None


def test_concurrent_guidance_is_isolated_and_inherited_by_worker_calls(profile):
    barrier = threading.Barrier(2)
    snapshots = [capture("software-data"), capture("finance-consulting")]

    def run(snapshot):
        with config.use_context(config.default_context()):
            industries.bind(snapshot)
            style.activate(**snapshot.styles)
            wrapped = config.run_in_context(rewrite._system)
            barrier.wait(timeout=10)
            return wrapped(), config.TAG_ALIASES.get("dcf")

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(run, snapshots))
    assert "Profile target field: Software & Data" in results[0][0]
    assert results[0][1] is None
    assert "Profile target field: Finance & Consulting" in results[1][0]
    assert results[1][1] == "discounted cash flow"
    assert industries.active() is None


@pytest.mark.parametrize("target", list(industries.catalog()))
def test_all_stages_receive_field_guidance_with_unchanged_output_schemas(profile, monkeypatch, target):
    snapshot = capture(target)
    industries.bind(snapshot)
    style.activate(**snapshot.styles)
    resume = synthetic_resume()
    requirements = jd.JobRequirements(title="Analyst", seniority="entry")
    calls = {}

    class Messages:
        def __init__(self, purpose):
            self.purpose = purpose

        def parse(self, **kwargs):
            calls[self.purpose] = kwargs
            output = {
                "extract": requirements,
                "score": rewrite.ScoreTable(scores=[]),
                "facets": facets.FacetSelection(),
                "rewrite": rewrite.RewriteResult(bullets=[]),
                "expand": expand.ExpansionLLMResult(entries=[]),
                "skills": skills.SkillsSelectionLLM(selected=[]),
                "cover": coverletter.CoverLetterLLM(paragraphs=[]),
            }[self.purpose]
            return SimpleNamespace(parsed_output=output, stop_reason="end_turn")

    monkeypatch.setattr(llm, "client_for", lambda purpose: SimpleNamespace(messages=Messages(purpose)))
    jd.extract("Analyst position", use_cache=False)
    rewrite.score_table(resume.all_bullets(), requirements, use_cache=False)
    facets.select_facets(resume, requirements, use_cache=False)
    rewrite.rewrite_bullets(resume.all_bullets(), requirements, char_budget=300,
                            repair_widows=False, repair_verbs=False)
    expand.expand_experience(resume, requirements, use_cache=False)
    skills.select_skills(resume, requirements, use_cache=False)
    coverletter._call_model(resume=resume, requirements=requirements,
                            bullets={b.id: b.text for b in resume.all_bullets()},
                            jd_text="Analyst position", word_band=(300, 380))
    assert set(calls) == set(industries.STAGES)
    for stage, kwargs in calls.items():
        assert f"Profile target field: {snapshot.label}" in kwargs["system"]
        assert kwargs["system"] == snapshot.systems[stage]
        assert "Candidate claims must come" in kwargs["system"]
    assert "<entry_context>" in calls["rewrite"]["messages"][0]["content"]


def test_accurate_repeated_verb_can_survive_repair_without_losing_metrics(profile, monkeypatch):
    industries.bind(capture())
    sources = {
        "a": Bullet(id="a", text="Analyzed 12 records using Excel.", tags=["excel"]),
        "b": Bullet(id="b", text="Analyzed 20 records using Excel.", tags=["excel"]),
    }
    calls = []

    class Messages:
        def parse(self, **kwargs):
            calls.append(kwargs)
            reply = rewrite.RewriteResult(bullets=[rewrite.RewrittenBullet(id="b", text=sources["b"].text)])
            return SimpleNamespace(parsed_output=reply, stop_reason="end_turn")

    monkeypatch.setattr(llm, "client_for", lambda _: SimpleNamespace(messages=Messages()))
    original = {bid: bullet.text for bid, bullet in sources.items()}
    result, _, changed, _ = rewrite._polish(original, sources,
                                           jd.JobRequirements(title="Analyst", seniority="entry"),
                                           repair_widows=False)
    assert result == original and changed == 0
    assert "Keep the original bullet unchanged" in calls[0]["messages"][0]["content"]


def test_thin_expansion_stays_short_and_fabricated_tools_are_dropped(profile):
    industries.bind(capture())
    entry = synthetic_resume().experience[0]
    entry.bullets = [Bullet(id="thin", text="Analyzed records using Excel.", tags=["excel"])]
    accepted, _ = expand._accept_bullets(entry, [entry.bullets[0].text], char_limit=2000)
    assert accepted == [entry.bullets[0].text]
    assert sum(map(len, accepted)) < 100
    accepted, warnings = expand._accept_bullets(entry, ["Analyzed records using Bloomberg."], char_limit=2000)
    assert accepted == [] and warnings


def test_simulation_and_forecast_context_remains_visible_and_numeric_guards_bind(profile):
    resume = synthetic_resume()
    entry = resume.projects[0]
    entry.name = "Coursework: simulated portfolio forecast"
    bullet = Bullet(id="simulated", text="Forecasted a simulated $10M portfolio using Excel.", tags=["excel"])
    entry.bullets = [bullet]
    snapshot = industries.capture("finance-consulting", {"rewrite": None, "expand": None, "cover": None}, resume=resume)
    industries.bind(snapshot)
    assert "simulated portfolio forecast" in rewrite._format_bullets([bullet], 300)
    assert "forecasts are not realized results" in rewrite._system()
    assert rewrite.guard_offenders([bullet], "Forecasted a simulated $20M portfolio using Excel.")
