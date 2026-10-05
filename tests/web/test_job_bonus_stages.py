"""The post-fit bonus stages (expansion, skills, cover letter) run at the same time."""

from __future__ import annotations

import contextlib
import threading
from types import SimpleNamespace

from resume_tailor import config
from resume_tailor.web import job_tailor_run
from resume_tailor.web.schemas import JobSettings


def _run(**settings) -> job_tailor_run._TailorJobRun:
    job = SimpleNamespace(settings=JobSettings(**settings), emit=lambda event: None)
    return job_tailor_run._TailorJobRun(job)


def test_expansion_skills_and_cover_letter_overlap(monkeypatch):
    # All three must be inside their stage at once to pass; run one after another, the
    # barrier times out and the stage records a failure instead.
    barrier = threading.Barrier(3, timeout=5)
    ran: dict[str, str] = {}
    cover_thread: list[int] = []

    def stage(name: str):
        def body(self) -> None:
            try:
                barrier.wait()
                ran[name] = config.active_workspace_id() or "ok"
            except threading.BrokenBarrierError:
                ran[name] = "sequential"
            if name == "cover":
                cover_thread.append(threading.get_ident())
        return body

    for name, method in (
        ("expand", "_expand"), ("skills", "_select_skills"), ("cover", "_draft_cover_letter"),
    ):
        monkeypatch.setattr(job_tailor_run._TailorJobRun, method, stage(name))

    _run(no_expand=False, cover_letter=True)._bonus_artifacts()

    assert set(ran) == {"expand", "skills", "cover"}
    assert "sequential" not in ran.values()
    assert cover_thread == [threading.get_ident()], "the cover letter (Word COM) stays here"


def test_a_failing_stage_does_not_stop_the_others(monkeypatch):
    done: list[str] = []

    def boom(self) -> None:
        raise RuntimeError("expand exploded")

    monkeypatch.setattr(job_tailor_run._TailorJobRun, "_expand", boom)
    monkeypatch.setattr(
        job_tailor_run._TailorJobRun, "_select_skills", lambda self: done.append("skills"),
    )
    monkeypatch.setattr(
        job_tailor_run._TailorJobRun, "_draft_cover_letter", lambda self: done.append("cover"),
    )

    with contextlib.suppress(RuntimeError):  # Real stages swallow their own errors.
        _run(no_expand=False, cover_letter=True)._bonus_artifacts()

    assert sorted(done) == ["cover", "skills"]


def test_skipped_stages_are_not_started(monkeypatch):
    started: list[str] = []
    for method in ("_expand", "_select_skills", "_draft_cover_letter"):
        monkeypatch.setattr(
            job_tailor_run._TailorJobRun, method,
            lambda self, m=method: started.append(m),
        )

    _run(no_expand=True, no_skills=True, cover_letter=False)._bonus_artifacts()

    assert started == []
