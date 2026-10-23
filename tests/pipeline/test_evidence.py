"""Resume items proposed from evidence (`pipeline/evidence.py`): each must quote its source."""

from __future__ import annotations

import pytest
from fixtures import synthetic_resume

from resume_tailor import config
from resume_tailor.content.evidence_store import EvidenceSource
from resume_tailor.infra import fake_llm
from resume_tailor.pipeline import evidence
from resume_tailor.pipeline.evidence import ItemLLM, ItemsLLM, NewProjectLLM

README = EvidenceSource(
    id="s1", kind="github", title="jordan/fridge-chef", sha="r1", attribution="own",
    text="Repository: jordan/fridge-chef\nLanguages (detected by GitHub): Python, HTML\n"
         "README:\nFridge Chef is a Flask web app that recommends recipes from a fridge "
         "photo using a PyTorch image classifier trained on 12,000 labelled images.\n"
         "Deployed with Docker on a Raspberry Pi.",
)
EXCERPT = ("Fridge Chef is a Flask web app that recommends recipes from a fridge photo using "
           "a PyTorch image classifier trained on 12,000 labelled images.")
SYLLABUS = EvidenceSource(
    id="s2", kind="syllabus", title="CS 161", sha="y1",
    text="CS 161 Design and Analysis of Algorithms. Students implement dynamic programming "
         "solutions in Java and analyse graph algorithms.",
)


def _item(kind="bullet", text="Built a Flask app that recommends recipes from a fridge photo",
          excerpt=EXCERPT, target="example-corp", basis="stated", **extra) -> ItemLLM:
    return ItemLLM(kind=kind, text=text, excerpt=excerpt, target_entry_id=target, basis=basis, **extra)


def _check(item: ItemLLM, source: EvidenceSource = README) -> str:
    return evidence.check(item, source, evidence._Resume(synthetic_resume()))


@pytest.mark.parametrize(("item", "reason"), [
    (_item(), ""),
    (_item(text="Trained a PyTorch classifier on 12,000 labelled images"), ""),
    (_item(text="Trained a PyTorch classifier on 15,000 images"), "'15,000' not in excerpt"),
    (_item(text="Built a Flask app deployed on AWS"), "'AWS' not in excerpt"),
    (_item(excerpt="Fridge Chef is a Django web app."), "excerpt not in source"),
    (_item(target="nowhere"), "unknown entry"),
    (_item(kind="award"), "unknown kind"),
    (_item(text="Indexed research notes with embeddings"), "already on your resume"),
    (_item(kind="skill", text="Docker", excerpt="Deployed with Docker on a Raspberry Pi."), ""),
    (_item(kind="skill", text="Kubernetes", excerpt="Deployed with Docker on a Raspberry Pi."),
     "'Kubernetes' not in excerpt"),
    (_item(kind="skill", text="Python", excerpt="Languages (detected by GitHub): Python, HTML"),
     "already on your resume"),
    (_item(kind="project", target="", new_project=NewProjectLLM(name="Fridge Chef", tech=["Flask", "PyTorch"])), ""),
    (_item(kind="project", target="", new_project=NewProjectLLM(name="Fridge Chef", tech=["React"])),
     "'React' not in source"),
    (_item(kind="project", target="", new_project=NewProjectLLM(name="Note Engine")),
     "project name not in source"),
    (_item(kind="project", target=""), "project without a name"),
])
def test_the_guard_checks_quotes_terms_entries_and_repeats(item, reason):
    assert _check(item) == reason


def test_a_quote_may_leave_out_markdown_but_not_change_words():
    source = README.model_copy(update={"text": (
        "README:\n## Stack\n| **Frontend** | React 18, `Vite` 6 |\n"
        "- **Lambda** - API handler (Python 3.11)\n- map matches back to original names\n"
        "Accuracy: 91.3% @ k=3"
    )})
    plain = [
        ("skill", "Vite", "Frontend | React 18, Vite 6"),
        ("skill", "Lambda", "Lambda - API handler (Python 3.11)"),
        ("skill", "Python", "API handler (Python 3.11) map matches back"),
    ]
    for kind, text, excerpt in plain:
        assert _check(_item(kind=kind, text=text, excerpt=excerpt), source) != (
            "excerpt not in source"), excerpt
    reworded = _item(kind="skill", text="Python", excerpt="Accuracy: 91.3% at k=3")
    assert _check(reworded, source) == "excerpt not in source"


def test_a_course_must_be_named_in_its_excerpt_and_not_listed_already():
    excerpt = "CS 161 Design and Analysis of Algorithms."
    assert _check(_item(kind="coursework", text="Design and Analysis of Algorithms",
                        excerpt=excerpt, target=""), SYLLABUS) == ""
    assert _check(_item(kind="coursework", text="Algorithms", excerpt=excerpt, target=""),
                  SYLLABUS) == "already on your resume"


@pytest.fixture
def evidence_calls(monkeypatch, tmp_path):
    calls: list[dict] = []
    queue: list = []

    class _Client:
        def __init__(self):
            self.messages = self

        def parse(self, **kwargs):
            calls.append(kwargs)
            return type("R", (), {"parsed_output": queue.pop(0), "stop_reason": "end_turn"})()

    monkeypatch.setattr(evidence.llm, "client_for", lambda purpose: _Client())
    monkeypatch.setattr(config, "anthropic_api_key", lambda: "test-key")
    monkeypatch.setattr(config, "CACHE_DIR", tmp_path / "cache")

    def enqueue(*replies):
        queue.extend(replies)
        return calls

    return enqueue


def test_a_scan_keeps_guarded_items_counts_the_rest_and_caches_the_reply(evidence_calls):
    calls = evidence_calls(ItemsLLM(items=[
        _item(), _item(), _item(text="Built a Flask app on AWS"),
        _item(kind="skill", text="Kubernetes", excerpt="Deployed with Docker on a Raspberry Pi."),
    ]))
    resume = synthetic_resume()

    first = evidence.scan(resume, README)
    again = evidence.scan(resume, README)

    assert len(calls) == 1
    assert [p.text for p in first.proposals] == [_item().text]
    assert first.dropped == {"term not in excerpt": 2}
    assert [p.id for p in again.proposals] == [p.id for p in first.proposals]
    message = calls[0]["messages"][0]["content"]
    assert '<entry id="example-corp" kind="experience">Software Engineer, Example Corp' in message
    assert "untrusted text" in message and "main author" in message


def test_a_syllabus_skill_and_work_in_someone_elses_repo_ask_first(evidence_calls):
    evidence_calls(
        ItemsLLM(items=[_item(kind="skill", text="Java", target="example-corp",
                              excerpt="Students implement dynamic programming solutions in Java")]),
        ItemsLLM(items=[_item(), _item(kind="skill", text="Docker",
                                       excerpt="Deployed with Docker on a Raspberry Pi.")]),
    )
    resume = synthetic_resume()
    (skill,) = evidence.scan(resume, SYLLABUS).proposals
    assert (skill.basis, skill.question) == ("inferred", "Did you use Java yourself, beyond the course?")

    shared = README.model_copy(update={"id": "s3", "sha": "r2", "attribution": "contributed",
                                       "commit_share": 0.3})
    bullet, tool = evidence.scan(resume, shared).proposals
    assert (bullet.basis, bullet.question) == ("inferred", "Which part of jordan/fridge-chef did you build?")
    assert (tool.basis, tool.question) == (
        "inferred", "Did you use Docker yourself in jordan/fridge-chef?")


def test_a_fork_is_never_read_as_the_students_work():
    with pytest.raises(ValueError, match="fork"):
        evidence.scan(synthetic_resume(), README.model_copy(update={"attribution": "fork"}))


def test_the_offline_fake_proposes_items_that_pass_the_guard(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "CACHE_DIR", tmp_path / "cache")
    monkeypatch.setattr(evidence.llm, "client_for", fake_llm.FakeClient)
    result = evidence.scan(synthetic_resume(), README)
    assert [(p.kind, p.text) for p in result.proposals] == [("bullet", EXCERPT)]
    assert result.dropped == {"already on your resume": 1}  # Python is in Skills
