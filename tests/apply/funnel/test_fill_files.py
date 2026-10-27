"""A fill uploads read-only copies taken when it started, and "What was sent" keeps the
ones it attached (audit #10, #11, #34)."""

from __future__ import annotations

import hashlib
import os
import stat

import pytest

from resume_tailor import config
from resume_tailor.apply.forms import submit_guard
from resume_tailor.apply.funnel import attempts, fill_files, store, store_models
from resume_tailor.apply.funnel.packet_models import Packet, PreparationManifest, PreparedArtifact


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@pytest.fixture
def run_dir(tmp_path):
    run = tmp_path / "run"
    run.mkdir()
    (run / "tailored.pdf").write_bytes(b"%PDF resume")
    (run / "cover.pdf").write_bytes(b"%PDF cover")
    return run


def _packet(run, **recorded):
    artifacts = {"resume_pdf": str(run / "tailored.pdf"), "cover_pdf": str(run / "cover.pdf")}
    digests = {"resume_pdf": _sha(b"%PDF resume"), "cover_pdf": _sha(b"%PDF cover"), **recorded}
    manifest = PreparationManifest(artifacts=[
        PreparedArtifact(purpose=kind, path=path, filename="x", mime_type="application/pdf",
                         sha256=digests[kind])
        for kind, path in artifacts.items()
    ])
    return Packet(job_id="run1", built_at="now", artifacts=artifacts, preparation=manifest)


def test_each_fill_uploads_its_own_read_only_copies(run_dir):
    first = _packet(run_dir)
    folder = fill_files.pin(first, "app-1")
    assert folder == config.APPLICATIONS_OUTPUT_DIR / "app-1" / "fills" / "1"
    resume = folder / "resume_pdf" / "tailored.pdf"
    assert first.artifacts["resume_pdf"] == str(resume) and first.pinned_dir == str(folder)
    assert not os.stat(resume).st_mode & stat.S_IWRITE
    # Re-rendering the resume while the fill runs changes nothing it sends.
    (run_dir / "tailored.pdf").write_bytes(b"%PDF edited")
    assert resume.read_bytes() == b"%PDF resume"
    second = _packet(run_dir, resume_pdf=_sha(b"%PDF edited"))
    assert fill_files.pin(second, "app-1").name == "2"


def test_a_file_that_changed_since_the_packet_was_built_is_refused(run_dir):
    stale = _packet(run_dir, resume_pdf=_sha(b"%PDF older"))
    with pytest.raises(fill_files.Changed):
        fill_files.pin(stale, "app-1")


def test_a_changed_file_rebuilds_the_packet_once(run_dir):
    builds = [_packet(run_dir, resume_pdf=_sha(b"%PDF older")), _packet(run_dir)]
    notes = []
    pkt = fill_files.pinned_packet(lambda: builds.pop(0), "app-1", progress=notes.append)
    assert pkt.pinned_dir and builds == [] and notes == [
        "a prepared file changed; rebuilding the packet"
    ]
    with pytest.raises(fill_files.Changed):
        fill_files.pinned_packet(lambda: _packet(run_dir, cover_pdf="0" * 64), "app-1")


def test_a_cover_letter_written_during_the_fill_is_pinned_too(run_dir):
    pkt = _packet(run_dir)
    del pkt.artifacts["cover_pdf"]
    folder = fill_files.pin(pkt, "app-1")
    pkt.artifacts["cover_pdf"] = str(run_dir / "cover.pdf")
    fill_files.pin_more(pkt, ("cover_pdf", "cover_docx"))
    assert pkt.artifacts["cover_pdf"] == str(folder / "cover_pdf" / "cover.pdf")


def test_what_was_sent_keeps_the_exact_files_the_app_attached(tmp_path, monkeypatch, run_dir):
    monkeypatch.setattr(config, "OUTPUT_DIR", tmp_path / "output")
    pkt = _packet(run_dir)
    fill_files.pin(pkt, "job-1")
    (run_dir / "tailored.pdf").write_bytes(b"%PDF edited after the fill")
    app = store_models.Application(
        source="t", source_job_id="job-1", company="Acme", role="Analyst", status="ready",
        fill={"uploads": [
            {"purpose": "resume", "verified": True, "uploaded_by_app": True,
             "artifact_path": pkt.artifacts["resume_pdf"]},
            {"purpose": "cover_letter", "verified": False, "uploaded_by_app": False,
             "artifact_path": pkt.artifacts["cover_pdf"]},
        ]},
    )
    store.set_status(app, "submitted", note=submit_guard.AUTO_NOTE)
    [attempt] = app.attempts
    assert attempt.attached == {"attached/resume/tailored.pdf": _sha(b"%PDF resume")}
    copied = (config.APPLICATIONS_OUTPUT_DIR / "job-1" / "attempts" / "1" / "attached"
              / "resume" / "tailored.pdf")
    assert copied.read_bytes() == b"%PDF resume"


def _prepared_run(job_id: str = "run1"):
    """A run folder where `fill_files` looks for the run's own files."""
    run = config.OUTPUT_DIR / "jobs" / job_id
    run.mkdir(parents=True)
    (run / "tailored.pdf").write_bytes(b"%PDF resume")
    (run / "cover.pdf").write_bytes(b"%PDF cover")
    (run / "bullets.json").write_text('{"b1": "Built the first version"}', encoding="utf-8")
    (run / "cover.json").write_text('{"paragraphs": ["First letter"]}', encoding="utf-8")
    return run


def test_the_bullets_kept_are_those_of_the_resume_the_app_attached(tmp_path, monkeypatch):
    """A Prepare between the fill and the mark rewrites the run folder; "What was sent"
    and interview prep keep the bullets of the resume on the form (audit review #8)."""
    from resume_tailor.apply.funnel import sent_copy

    monkeypatch.setattr(config, "OUTPUT_DIR", tmp_path / "output")
    run = _prepared_run()
    pkt = _packet(run)
    fill_files.pin(pkt, "job-3")
    (run / "tailored.pdf").write_bytes(b"%PDF re-prepared")
    (run / "bullets.json").write_text('{"b1": "Never uploaded"}', encoding="utf-8")
    (run / "cover.json").write_text('{"paragraphs": ["Never uploaded"]}', encoding="utf-8")
    app = store_models.Application(
        source="t", source_job_id="job-3", company="Acme", role="Analyst", status="ready",
        job_id="run1",
        fill={"uploads": [{"purpose": "resume", "verified": True, "uploaded_by_app": True,
                           "artifact_path": pkt.artifacts["resume_pdf"]}]},
    )
    store.set_status(app, "submitted", note=submit_guard.AUTO_NOTE)
    [attempt] = app.attempts
    assert attempt.files["tailored.pdf"] == _sha(b"%PDF resume")
    sent = sent_copy.load(app)
    assert sent.attempt == 1 and sent.bullets == {"b1": "Built the first version"}
    assert sent.cover_letter == "First letter"
    packet = config.APPLICATIONS_OUTPUT_DIR / "job-3" / "attempts" / "1" / "packet.json"
    assert '"pinned_dir"' in packet.read_text(encoding="utf-8")  # the fill's own packet


def test_two_attached_files_with_one_name_are_both_kept(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "OUTPUT_DIR", tmp_path / "output")
    uploads = []
    for purpose, body in (("transcript", b"%PDF transcript"), ("portfolio", b"%PDF portfolio")):
        source = tmp_path / purpose / "document.pdf"
        source.parent.mkdir()
        source.write_bytes(body)
        uploads.append({"purpose": purpose, "verified": True, "uploaded_by_app": True,
                        "artifact_path": str(source)})
    app = store_models.Application(
        source="t", source_job_id="job-4", company="Acme", role="Analyst", status="ready",
        fill={"uploads": uploads},
    )
    store.set_status(app, "submitted", note=submit_guard.AUTO_NOTE)
    assert app.attempts[0].attached == {
        "attached/transcript/document.pdf": _sha(b"%PDF transcript"),
        "attached/portfolio/document.pdf": _sha(b"%PDF portfolio"),
    }


def test_a_manual_mark_without_app_uploads_keeps_only_prepared_files(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "OUTPUT_DIR", tmp_path / "output")
    app = store_models.Application(
        source="t", source_job_id="job-2", company="Acme", role="Analyst", status="ready",
    )
    store.set_status(app, "submitted", note="Marked by you")
    assert app.attempts[0].attached == {} and not app.attempts[0].confirmed
    assert attempts.ATTACHED == "attached/"
