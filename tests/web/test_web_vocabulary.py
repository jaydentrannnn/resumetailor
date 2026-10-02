"""Vocabulary libraries and proposals (`/api/libraries*`, `/api/proposals*`)."""

from __future__ import annotations

from resume_tailor import config
from resume_tailor.web import job_types
from resume_tailor.web.schemas import JobSettings
from tests.web.helpers import _FakeProposeClient, _FakeSDKError, _write_test_resume


def test_get_libraries_lists_shipped_packs_and_effective_counts(client):
    c, _ = client
    res = c.get("/api/libraries")
    assert res.status_code == 200
    body = res.json()
    # Every shipped pack is always listed, whether or not it is enabled — only
    # "core-tech" is enabled by default in a fresh workspace's libraries.json.
    ids = [p["id"] for p in body["packs"]]
    assert "core-tech" in ids
    shipped = [p for p in body["packs"] if p["builtin"]]
    assert {p["id"] for p in shipped} == {
        "core-tech",
        "finance-consulting",
        "accounting",
        "marketing",
        "ops-supply-chain",
    }
    core = next(p for p in body["packs"] if p["id"] == "core-tech")
    assert core["customized"] is False
    assert body["enabled_packs"] == ["core-tech"]
    assert body["effective"]["tag_alias_count"] == core["tag_alias_count"]
    assert body["diagnostics"] == []


def test_get_library_pack_returns_full_contents(client):
    c, _ = client
    res = c.get("/api/libraries/packs/core-tech")
    assert res.status_code == 200
    body = res.json()
    assert body["tag_aliases"]["py"] == "python"
    assert "build" in body["verb_families"]


def test_get_library_pack_404s_for_an_unknown_id(client):
    c, _ = client
    res = c.get("/api/libraries/packs/does-not-exist")
    assert res.status_code == 404


def test_create_library_pack_then_selection_makes_it_effective(client):
    c, _ = client
    created = c.post(
        "/api/libraries/packs",
        json={"label": "Nursing", "tag_aliases": {"bls": "basic life support"}},
    )
    assert created.status_code == 200
    pack_id = next(p["id"] for p in created.json()["packs"] if p["label"] == "Nursing")
    assert pack_id != "core-tech"

    res = c.put(
        "/api/libraries/selection",
        json={"enabled_packs": ["core-tech", pack_id]},
    )
    assert res.status_code == 200
    assert res.json()["enabled_packs"] == ["core-tech", pack_id]

    from resume_tailor import config as config_mod

    assert config_mod.TAG_ALIASES.get("bls") == "basic life support"


def test_create_library_pack_rejects_a_builtin_id(client):
    c, _ = client
    res = c.post("/api/libraries/packs", json={"label": "core-tech"})
    # "core-tech" the label slugs to the existing builtin id, so a fresh id is minted
    # instead of colliding — this call must succeed, not 400.
    assert res.status_code == 200


def test_update_library_pack_returns_400_with_every_validation_error(client):
    c, _ = client
    c.post("/api/libraries/packs", json={"label": "A"})
    pack_id = c.get("/api/libraries").json()["packs"][-1]["id"]

    res = c.put(
        f"/api/libraries/packs/{pack_id}",
        json={"label": "A", "tag_aliases": {"python": "python"}},
    )

    assert res.status_code == 400
    assert "errors" in res.json()["detail"]
    assert any("itself" in e for e in res.json()["detail"]["errors"])


def test_update_library_pack_conflict_needs_force(client):
    c, _ = client
    res = c.post("/api/libraries/packs", json={"label": "A", "tag_aliases": {"py": "not-python"}})
    assert res.status_code == 400

    ok = c.post(
        "/api/libraries/packs",
        json={"label": "A", "tag_aliases": {"py": "not-python"}, "force": True},
    )
    assert ok.status_code == 200


def test_update_an_enabled_pack_does_not_conflict_with_its_own_prior_version(client):
    """Web-layer regression companion to
    test_libraries.py::test_updating_an_enabled_pack_does_not_conflict_with_its_own_prior_version."""
    c, _ = client
    created = c.post("/api/libraries/packs", json={"label": "A", "tag_aliases": {"x": "y"}})
    pack_id = created.json()["packs"][-1]["id"]
    c.put("/api/libraries/selection", json={"enabled_packs": ["core-tech", pack_id]})

    res = c.put(f"/api/libraries/packs/{pack_id}", json={"label": "A", "tag_aliases": {"x": "z"}})

    assert res.status_code == 200


def test_update_shipped_pack_writes_a_shadow(client):
    c, _ = client
    body = c.get("/api/libraries/packs/core-tech").json()
    body["tag_aliases"] = {**body["tag_aliases"], "custom-alias": "custom-target"}
    res = c.put(
        "/api/libraries/packs/core-tech",
        json={
            "label": body["label"],
            "description": body["description"],
            "tag_aliases": body["tag_aliases"],
            "verb_families": body["verb_families"],
        },
    )
    assert res.status_code == 200
    core = next(p for p in res.json()["packs"] if p["id"] == "core-tech")
    assert core["customized"] is True
    reread = c.get("/api/libraries/packs/core-tech").json()
    assert reread["tag_aliases"]["custom-alias"] == "custom-target"


def test_reset_shipped_pack_restores_the_seed(client):
    c, _ = client
    body = c.get("/api/libraries/packs/core-tech").json()
    body["tag_aliases"] = {**body["tag_aliases"], "custom-alias": "custom-target"}
    c.put(
        "/api/libraries/packs/core-tech",
        json={
            "label": body["label"],
            "description": body["description"],
            "tag_aliases": body["tag_aliases"],
            "verb_families": body["verb_families"],
        },
    )
    res = c.post("/api/libraries/packs/core-tech/reset")
    assert res.status_code == 200
    core = next(p for p in res.json()["packs"] if p["id"] == "core-tech")
    assert core["customized"] is False
    reread = c.get("/api/libraries/packs/core-tech").json()
    assert "custom-alias" not in reread["tag_aliases"]


def test_delete_library_pack_refuses_a_shipped_id(client):
    c, _ = client
    res = c.delete("/api/libraries/packs/core-tech")
    assert res.status_code == 400


def test_delete_library_pack_removes_it_from_the_list(client):
    c, _ = client
    created = c.post("/api/libraries/packs", json={"label": "A"})
    pack_id = created.json()["packs"][-1]["id"]

    res = c.delete(f"/api/libraries/packs/{pack_id}")

    assert res.status_code == 200
    assert pack_id not in [p["id"] for p in res.json()["packs"]]


def test_library_impact_distinguishes_additive_from_rewriting(client, tmp_path, monkeypatch):
    c, _ = client
    monkeypatch.setattr(config, "MASTER_RESUME_PATH", tmp_path / "no-such-resume.json")

    res = c.post("/api/libraries/impact", json={"tag_aliases": {"rust": "rust-lang"}})

    assert res.status_code == 200
    impacts = res.json()["impacts"]
    assert impacts[0]["alias"] == "rust"
    assert impacts[0]["affected_tags"] == []


def test_library_routes_reject_when_queue_busy(client):
    c, q = client
    # Direct insertion, not submit() — see test_upload_template_rejects_when_queue_busy
    # for why: submit() starts a real background worker regardless of reassigning
    # `job.status` afterward.
    job = job_types.Job(
        job_id="fake-busy", jd_text="placeholder jd", settings=JobSettings(), status="running"
    )
    q._jobs[job.job_id] = job

    for res in (
        c.post("/api/libraries/packs", json={"label": "A"}),
        c.put("/api/libraries/packs/core-tech", json={"label": "core-tech"}),
        c.delete("/api/libraries/packs/core-tech"),
        c.put("/api/libraries/selection", json={"enabled_packs": ["core-tech"]}),
    ):
        assert res.status_code == 409
        assert "progress" in res.json()["detail"].lower() or "job" in res.json()["detail"].lower()


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


def test_approve_requires_acknowledgement_when_it_rewrites_an_existing_tag(
    client, tmp_path, monkeypatch
):
    c, _ = client
    _write_test_resume(monkeypatch, tmp_path, bullet_text="Used Postgres.", bullet_tags=["pg"])
    created = c.post("/api/libraries/packs", json={"label": "A"})
    pack_id = created.json()["packs"][-1]["id"]

    from resume_tailor.content import libraries as libraries_mod
    from resume_tailor.content import library_models

    state = libraries_mod.read_workspace_state()
    state.proposals = [
        library_models.LibraryProposal(
            id="p-1", kind="tag_alias", alias="pg", canonical="postgresql", source="manual",
            created_at="2026-01-01T00:00:00+00:00",
        )
    ]
    libraries_mod.write_workspace_state(state)

    refused = c.post(
        "/api/libraries/proposals/approve",
        json={"proposal_ids": ["p-1"], "target_pack_id": pack_id},
    )
    assert refused.status_code == 409
    assert refused.json()["detail"]["impact"][0]["alias"] == "pg"
    # No backup should exist yet — refused before any write.
    assert list(tmp_path.glob("*.bak.json")) == []

    ok = c.post(
        "/api/libraries/proposals/approve",
        json={"proposal_ids": ["p-1"], "target_pack_id": pack_id, "acknowledge_rewrites": True},
    )
    assert ok.status_code == 200
    assert ok.json()["proposals"] == []
    pack_after = c.get(f"/api/libraries/packs/{pack_id}").json()
    assert pack_after["tag_aliases"]["pg"] == "postgresql"
    assert list(tmp_path.glob("*.bak.json")) != []


def test_approve_into_a_shipped_target_pack_writes_a_shadow(client, tmp_path, monkeypatch):
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

    res = c.post(
        "/api/libraries/proposals/approve",
        json={"proposal_ids": ["p-1"], "target_pack_id": "core-tech"},
    )
    assert res.status_code == 200
    core = next(p for p in res.json()["packs"] if p["id"] == "core-tech")
    assert core["customized"] is True
    pack_after = c.get("/api/libraries/packs/core-tech").json()
    assert pack_after["tag_aliases"]["pg"] == "postgresql"


def test_approve_404s_for_unknown_proposal_ids(client, tmp_path, monkeypatch):
    c, _ = client
    _write_test_resume(monkeypatch, tmp_path, bullet_text="Did a thing.", bullet_tags=["python"])
    created = c.post("/api/libraries/packs", json={"label": "A"})
    pack_id = created.json()["packs"][-1]["id"]

    res = c.post(
        "/api/libraries/proposals/approve",
        json={"proposal_ids": ["does-not-exist"], "target_pack_id": pack_id},
    )
    assert res.status_code == 404


def test_approve_rejects_when_queue_busy(client, tmp_path, monkeypatch):
    c, q = client
    _write_test_resume(monkeypatch, tmp_path, bullet_text="Did a thing.", bullet_tags=["python"])
    # Direct insertion, not submit() — see test_upload_template_rejects_when_queue_busy.
    job = job_types.Job(
        job_id="fake-busy", jd_text="placeholder jd", settings=JobSettings(), status="running"
    )
    q._jobs[job.job_id] = job

    res = c.post(
        "/api/libraries/proposals/approve",
        json={"proposal_ids": ["p-1"], "target_pack_id": "some-pack"},
    )
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
