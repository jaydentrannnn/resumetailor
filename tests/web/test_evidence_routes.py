"""Evidence routes (`web/routes/evidence.py`): nothing reaches the resume until accepted."""

from __future__ import annotations

import json

import pytest

from resume_tailor import config
from resume_tailor.content import resume_versions
from resume_tailor.importing import github_evidence
from resume_tailor.infra import fake_llm
from resume_tailor.pipeline import evidence
from resume_tailor.web.routes import evidence as evidence_routes

WRITEUP = ("Built a command-line tool that converts lecture notes into flashcards for "
           "spaced repetition.\nLanguages (detected by GitHub): Rust")


@pytest.fixture
def api(client, monkeypatch):
    c, _q = client
    monkeypatch.setattr(evidence.llm, "client_for", fake_llm.FakeClient)
    return c


def _add(api, text=WRITEUP, **extra) -> dict:
    response = api.post("/api/evidence/text", json={"kind": "writeup", "title": "Flashcards", "text": text, **extra})
    assert response.status_code == 200, response.text
    return response.json()


def _resume() -> dict:
    return json.loads(config.MASTER_RESUME_PATH.read_text(encoding="utf-8"))


def _bullets(resume: dict) -> dict[str, dict]:
    return {b["id"]: b for s in resume["sections"] if s["kind"] in ("experience", "project")
            for e in s["entries"] for b in e["bullets"]}


def test_a_document_is_scanned_on_add_and_changes_nothing_until_decided(api):
    before = config.MASTER_RESUME_PATH.read_text(encoding="utf-8")
    view = _add(api)

    (source,) = view["sources"]
    assert "text" not in source and source["chars"] > 50 and source["scanned_at"]
    assert [(p["kind"], p["state"]) for p in view["proposals"]] == [("bullet", "pending"), ("skill", "pending")]
    assert view["github_user"] == "jordanrivera"
    assert config.MASTER_RESUME_PATH.read_text(encoding="utf-8") == before


def test_add_to_resume_writes_the_edited_bullet_with_a_version_and_backup(api):
    bullet = _add(api)["proposals"][0]
    response = api.post(f"/api/evidence/proposals/{bullet['id']}/add", json={
        "text": "Built a Rust CLI that turns lecture notes into flashcards", "skills": ["Rust"],
    })
    assert response.status_code == 200, response.text
    body = response.json()

    added = _bullets(_resume())["exp_b2"]
    assert (added["text"], added["tags"]) == ("Built a Rust CLI that turns lecture notes into flashcards", ["Rust"])
    assert _bullets(body["resume"])["exp_b2"]["text"] == added["text"]
    assert resume_versions.list_versions()[0]["note"] == "added from evidence"
    assert list(config.MASTER_RESUME_PATH.parent.glob("master_resume.*.bak.json"))
    (decided,) = [p for p in body["evidence"]["proposals"] if p["id"] == bullet["id"]]
    assert (decided["state"], decided["added_to"]) == ("added", "bullet exp_b2")
    assert api.post(f"/api/evidence/proposals/{bullet['id']}/dismiss").status_code == 409


def test_matching_only_shows_beside_the_bullet_and_never_reaches_its_tags(api):
    skill = _add(api)["proposals"][1]
    assert api.post(f"/api/evidence/proposals/{_add(api)['proposals'][0]['id']}/matching-only",
                    json={}).status_code == 422

    view = api.post(f"/api/evidence/proposals/{skill['id']}/matching-only", json={}).json()

    assert view["matching"] == {"example-corp": ["Rust"]}
    assert api.get("/api/master-resume/skills").json()["evidence"] == {"exp_b1": ["Rust"]}
    assert _bullets(_resume())["exp_b1"]["tags"] == ["python"]

    view = api.post(f"/api/evidence/proposals/{skill['id']}/reopen").json()
    assert view["matching"] == {}
    assert next(p for p in view["proposals"] if p["id"] == skill["id"])["state"] == "pending"


def test_a_dismissed_item_stays_dismissed_when_the_source_is_scanned_again(api):
    view = _add(api)
    source_id, bullet = view["sources"][0]["id"], view["proposals"][0]
    api.post(f"/api/evidence/proposals/{bullet['id']}/dismiss")

    view = api.post(f"/api/evidence/sources/{source_id}/scan").json()

    states = {p["id"]: p["state"] for p in view["proposals"]}
    assert states[bullet["id"]] == "dismissed"
    assert list(states.values()).count("pending") == 1


def test_removing_a_source_keeps_decided_items(api):
    view = _add(api)
    source_id, skill = view["sources"][0]["id"], view["proposals"][1]
    api.post(f"/api/evidence/proposals/{skill['id']}/matching-only", json={})

    view = api.delete(f"/api/evidence/sources/{source_id}").json()

    assert view["sources"] == [] and [p["id"] for p in view["proposals"]] == [skill["id"]]
    assert api.delete(f"/api/evidence/sources/{source_id}").status_code == 404


def test_an_uploaded_file_is_read_and_a_bad_one_is_refused(api):
    ok = api.post("/api/evidence/file", data={"kind": "letter", "scan": "false"},
                  files={"file": ("letter.txt", WRITEUP.encode(), "text/plain")})
    assert ok.status_code == 200, ok.text
    assert [(s["title"], s["scanned_at"]) for s in ok.json()["sources"]] == [("letter", "")]
    bad = api.post("/api/evidence/file", files={"file": ("x.png", b"\x89PNG", "image/png")})
    assert bad.status_code == 422 and "Upload a .txt" in bad.json()["detail"]


def test_github_repos_are_listed_without_scanning_and_a_fork_is_never_scanned(api, monkeypatch):
    seen = {}

    def read(target, fetcher, *, user=""):
        seen["args"] = (target, user)
        return [
            github_evidence.Repo(owner="jordanrivera", name="cards", url="https://github.com/jordanrivera/cards",
                                 readme=WRITEUP, attribution="own", commit_share=1.0),
            github_evidence.Repo(owner="jordanrivera", name="lib", url="https://github.com/jordanrivera/lib",
                                 fork=True, attribution="fork"),
        ], []

    monkeypatch.setattr(evidence_routes.github_evidence, "read", read)
    view = api.post("/api/evidence/github", json={"target": "jordanrivera"}).json()

    assert seen["args"] == ("jordanrivera", "jordanrivera")
    assert [(s["title"], s["attribution"], s["scanned_at"]) for s in view["sources"]] == [
        ("jordanrivera/cards", "own", ""), ("jordanrivera/lib", "fork", ""),
    ]
    assert view["proposals"] == []
    fork = api.post(f"/api/evidence/sources/{view['sources'][1]['id']}/scan")
    assert fork.status_code == 422 and "fork" in fork.json()["detail"]


def test_a_github_failure_is_a_plain_error(api, monkeypatch):
    def read(*_a, **_k):
        raise github_evidence.GitHubError("GitHub's limit on reads was reached.")

    monkeypatch.setattr(evidence_routes.github_evidence, "read", read)
    response = api.post("/api/evidence/github", json={"target": "jordanrivera"})
    assert response.status_code == 422 and "limit" in response.json()["detail"]
