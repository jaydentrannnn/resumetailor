"""Vocabulary dictionary and proposals (`/api/libraries*`)."""

from __future__ import annotations

from resume_tailor import config
from resume_tailor.content import libraries as libraries_mod
from resume_tailor.content import library_models
from resume_tailor.web import job_types
from resume_tailor.web.schemas import JobSettings
from tests.web.helpers import _FakeProposeClient, _FakeSDKError, _write_test_resume


def _queue_busy(q) -> None:
    # Direct insertion, not submit() — see test_upload_template_rejects_when_queue_busy:
    # submit() starts a real background worker regardless of reassigning `job.status`.
    job = job_types.Job(
        job_id="fake-busy", jd_text="placeholder jd", settings=JobSettings(), status="running"
    )
    q._jobs[job.job_id] = job


def _propose(*proposals: library_models.LibraryProposal) -> None:
    state = libraries_mod.read_workspace_state()
    state.proposals = list(proposals)
    libraries_mod.write_workspace_state(state)


def _alias_proposal(alias: str, canonical: str, pid: str = "p-1") -> library_models.LibraryProposal:
    return library_models.LibraryProposal(
        id=pid, kind="tag_alias", alias=alias, canonical=canonical, source="manual",
        created_at="2026-01-01T00:00:00+00:00",
    )


def test_get_libraries_lists_terms_and_families_with_counts(client):
    c, _ = client
    body = c.get("/api/libraries").json()
    python = next(e for e in body["entries"] if e["kind"] == "term" and e["name"] == "python")
    assert python["builtin"] is True
    assert {"value": "py", "builtin": True, "hidden": False} in python["items"]
    assert any(e["kind"] == "family" and e["name"] == "build" for e in body["entries"])
    assert body["effective"]["tag_alias_count"] > 0
    assert body["diagnostics"] == []


def test_add_hide_and_remove_round_trip(client):
    c, _ = client
    res = c.post("/api/libraries/additions", json={"kind": "alias", "value": "PGX", "target": "postgresql"})
    assert res.status_code == 200
    assert config.canonical_tag("pgx") == "postgresql"

    assert c.post("/api/libraries/additions", json={"kind": "term", "value": "quuxware"}).status_code == 200
    assert c.post("/api/libraries/additions", json={"kind": "verb", "value": "zorped", "target": "build"}).status_code == 200
    assert config.verb_family("zorped") == "build"

    hidden = c.post("/api/libraries/hidden", json={"kind": "alias", "value": "py", "hidden": True})
    assert hidden.status_code == 200 and config.canonical_tag("py") == "py"

    removed = c.post("/api/libraries/additions/remove", json={"kind": "alias", "value": "pgx"})
    assert removed.status_code == 200 and config.canonical_tag("pgx") == "pgx"


def test_vocabulary_edits_are_app_wide_not_per_profile(client):
    c, _ = client
    c.post("/api/libraries/additions", json={"kind": "alias", "value": "pgx", "target": "postgresql"})
    assert libraries_mod.read_workspace_state().model_dump()["overrides"]["tag_aliases"] == {}
    assert libraries_mod.read_user_vocabulary().tag_aliases == {"pgx": "postgresql"}


def test_bad_additions_are_400_and_builtins_cannot_be_removed(client):
    c, _ = client
    assert c.post("/api/libraries/additions", json={"kind": "alias", "value": "py", "target": "pytorch"}).status_code == 400
    assert c.post("/api/libraries/additions/remove", json={"kind": "alias", "value": "py"}).status_code == 400
    assert c.post("/api/libraries/hidden", json={"kind": "alias", "value": "not-builtin"}).status_code == 400


def test_vocabulary_edits_reject_when_queue_busy(client):
    c, q = client
    _queue_busy(q)
    for res in (
        c.post("/api/libraries/additions", json={"kind": "term", "value": "quuxware"}),
        c.post("/api/libraries/additions/remove", json={"kind": "term", "value": "quuxware"}),
        c.post("/api/libraries/hidden", json={"kind": "alias", "value": "py"}),
    ):
        assert res.status_code == 409


def test_generate_proposals_finds_an_unknown_opening_verb(client, tmp_path, monkeypatch):
    from resume_tailor.pipeline import propose as propose_mod

    c, _ = client
    _write_test_resume(
        monkeypatch, tmp_path, bullet_text="Triaged 200 support tickets weekly.", bullet_tags=["python"]
    )
    calls: list[dict] = []
    parsed = propose_mod.VocabularyProposal(
        verb_families=[
            propose_mod.VerbProposal(verb="triaged", family="analyse", rationale="diagnostic work")
        ]
    )
    monkeypatch.setattr(propose_mod.llm, "client_for", lambda purpose: _FakeProposeClient(parsed, calls))

    res = c.post("/api/libraries/proposals", json={})

    assert res.status_code == 200
    body = res.json()
    assert len(calls) == 1
    assert len(body["proposals"]) == 1
    assert body["proposals"][0] == {
        "id": body["proposals"][0]["id"],
        "kind": "verb_family",
        "alias": None,
        "canonical": None,
        "verb": "triaged",
        "family": "analyse",
        "rationale": "diagnostic work",
        "source": "manual",
        "created_at": body["proposals"][0]["created_at"],
        "target_exists": True,
    }


def test_generate_proposals_makes_no_call_when_nothing_to_propose(client, tmp_path, monkeypatch):
    from resume_tailor.pipeline import propose as propose_mod

    c, _ = client
    _write_test_resume(monkeypatch, tmp_path, bullet_text="Designed a caching layer.", bullet_tags=["python"])

    def _fail(purpose):
        raise AssertionError("should not call the LLM when there is nothing to propose")

    monkeypatch.setattr(propose_mod.llm, "client_for", _fail)

    res = c.post("/api/libraries/proposals", json={})

    assert res.status_code == 200
    assert res.json()["proposals"] == []


def test_generate_proposals_llm_error_is_not_fatal(client, tmp_path, monkeypatch):
    from resume_tailor.pipeline import propose as propose_mod

    c, _ = client
    _write_test_resume(
        monkeypatch, tmp_path, bullet_text="Triaged 200 support tickets weekly.", bullet_tags=["python"]
    )

    def _raise(purpose):
        raise RuntimeError("model unavailable")

    monkeypatch.setattr(propose_mod.llm, "client_for", _raise)

    res = c.post("/api/libraries/proposals", json={})

    assert res.status_code == 200
    body = res.json()
    assert body["proposals"] == []
    assert body["warning"] and "model unavailable" in body["warning"]


def test_generate_proposals_non_runtimeerror_failure_is_not_fatal(client, tmp_path, monkeypatch):
    """Same as `test_generate_proposals_llm_error_is_not_fatal`, but with an exception
    type (like a real backend SDK error) that a narrower `except (LLMError, RuntimeError)`
    would have let escape as a 500 — see `_FakeSDKError` above."""
    from resume_tailor.pipeline import propose as propose_mod

    c, _ = client
    _write_test_resume(
        monkeypatch, tmp_path, bullet_text="Triaged 200 support tickets weekly.", bullet_tags=["python"]
    )

    def _raise(purpose):
        raise _FakeSDKError("Your credit balance is too low to access the Anthropic API.")

    monkeypatch.setattr(propose_mod.llm, "client_for", _raise)

    res = c.post("/api/libraries/proposals", json={})

    assert res.status_code == 200
    body = res.json()
    assert body["proposals"] == []
    assert body["warning"] and "credit balance" in body["warning"]


def test_approve_adds_to_an_existing_term_without_touching_the_resume(client, tmp_path, monkeypatch):
    c, _ = client
    _write_test_resume(monkeypatch, tmp_path, bullet_text="Used Postgres.", bullet_tags=["pgx"])
    before = config.MASTER_RESUME_PATH.read_bytes()
    _propose(_alias_proposal("pgx", "postgresql"))
    assert c.get("/api/libraries").json()["proposals"][0]["target_exists"] is True

    res = c.post("/api/libraries/proposals/approve", json={"proposal_ids": ["p-1"]})

    assert res.status_code == 200
    assert res.json()["proposals"] == []
    assert config.canonical_tag("pgx") == "postgresql"
    assert config.MASTER_RESUME_PATH.read_bytes() == before
    assert list(tmp_path.glob("*.bak.json")) == []


def test_approve_creates_a_new_term_or_follows_a_redirected_target(client, tmp_path, monkeypatch):
    c, _ = client
    _write_test_resume(monkeypatch, tmp_path, bullet_text="Did a thing.", bullet_tags=["python"])
    _propose(_alias_proposal("qxw", "quuxware"), _alias_proposal("pgx", "postgres sql", pid="p-2"))
    proposals = {p["id"]: p for p in c.get("/api/libraries").json()["proposals"]}
    assert proposals["p-1"]["target_exists"] is False

    res = c.post(
        "/api/libraries/proposals/approve",
        json={"proposal_ids": ["p-1", "p-2"], "targets": {"p-2": "postgresql"}},
    )

    assert res.status_code == 200
    assert config.canonical_tag("qxw") == "quuxware"
    assert config.canonical_tag("pgx") == "postgresql"


def test_approve_404s_for_unknown_proposal_ids(client, tmp_path, monkeypatch):
    c, _ = client
    _write_test_resume(monkeypatch, tmp_path, bullet_text="Did a thing.", bullet_tags=["python"])
    res = c.post("/api/libraries/proposals/approve", json={"proposal_ids": ["does-not-exist"]})
    assert res.status_code == 404


def test_approve_rejects_when_queue_busy(client, tmp_path, monkeypatch):
    c, q = client
    _write_test_resume(monkeypatch, tmp_path, bullet_text="Did a thing.", bullet_tags=["python"])
    # Direct insertion, not submit() — see test_upload_template_rejects_when_queue_busy.
    job = job_types.Job(
        job_id="fake-busy", jd_text="placeholder jd", settings=JobSettings(), status="running"
    )
    q._jobs[job.job_id] = job

    res = c.post("/api/libraries/proposals/approve", json={"proposal_ids": ["p-1"]})
    assert res.status_code == 409


def test_generate_and_reject_proceed_even_when_queue_busy(client, tmp_path, monkeypatch):
    """Unlike approve, generate/reject touch nothing effective — a running job must
    not block them."""
    c, q = client
    _write_test_resume(monkeypatch, tmp_path, bullet_text="Did a thing.", bullet_tags=["python"])
    # Direct insertion, not submit() — see test_upload_template_rejects_when_queue_busy.
    job = job_types.Job(
        job_id="fake-busy", jd_text="placeholder jd", settings=JobSettings(), status="running"
    )
    q._jobs[job.job_id] = job

    assert c.post("/api/libraries/proposals", json={}).status_code == 200
    assert c.post("/api/libraries/proposals/reject", json={"proposal_ids": []}).status_code == 200


def test_reject_moves_ids_to_rejected_and_they_are_never_reproposed(client, tmp_path, monkeypatch):
    from resume_tailor.content import libraries as libraries_mod
    from resume_tailor.content import library_models

    c, _ = client
    _write_test_resume(monkeypatch, tmp_path, bullet_text="Did a thing.", bullet_tags=["python"])

    state = libraries_mod.read_workspace_state()
    state.proposals = [
        library_models.LibraryProposal(
            id="p-1", kind="tag_alias", alias="pg", canonical="postgresql", source="manual",
            created_at="2026-01-01T00:00:00+00:00",
        )
    ]
    libraries_mod.write_workspace_state(state)

    res = c.post("/api/libraries/proposals/reject", json={"proposal_ids": ["p-1"]})

    assert res.status_code == 200
    assert res.json()["proposals"] == []
    reloaded = libraries_mod.read_workspace_state()
    assert reloaded.proposals == []
    assert len(reloaded.rejected) == 1
    assert reloaded.rejected[0].alias == "pg"
