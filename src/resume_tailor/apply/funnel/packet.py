"""Application packet assembly from a completed tailoring run.

Pure function of disk artifacts, the master resume, and the applicant profile — no LLM.
``build_packet`` reads ``run.json``, optional expansion/skills/cover/bullets JSON, and
paths to rendered documents; ``write_packet`` persists ``packet.json`` beside them.
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from resume_tailor import config
from resume_tailor.apply.answers import profile as profile_mod
from resume_tailor.apply.ats import ats_hints
from resume_tailor.content.data import MasterResume, load
from resume_tailor.pipeline.expand import ExpandedEntry, Expansion

from . import packet_fields, packet_models


def current_inputs_digest() -> str:
    profile, _seeded = profile_mod.load_profile()
    return packet_models.inputs_digest(profile, load())


def _experience_from_expansion(
    entries: list[ExpandedEntry],
) -> list[packet_models.PacketExperience]:
    """Map expansion artifact entries to packet experience rows."""
    rows: list[packet_models.PacketExperience] = []
    for entry in entries:
        description = "\n".join(f"• {bullet}" for bullet in entry.bullets)
        rows.append(
            packet_models.PacketExperience(
                employer=entry.company,
                title=entry.title,
                location=entry.location,
                start=entry.start,
                end=entry.end,
                current=entry.end.lower() in {"present", "current"},
                description=description,
                char_count=len(description),
                entry_key=entry.entry_key,
                source_entry_id=entry.entry_key.removeprefix("exp:"),
                bullets=list(entry.bullets),
                warnings=list(entry.warnings),
            )
        )
    return rows


def _experience_from_resume(resume: MasterResume) -> list[packet_models.PacketExperience]:
    """Build experience rows from the master resume with empty descriptions."""
    rows: list[packet_models.PacketExperience] = []
    for entry in resume.experience:
        rows.append(
            packet_models.PacketExperience(
                employer=entry.company,
                title=entry.title,
                location=entry.location,
                start=entry.start,
                end=entry.end,
                current=entry.end.lower() in {"present", "current"},
                description="",
                char_count=0,
                entry_key=f"exp:{entry.id}",
                source_entry_id=entry.id,
            )
        )
    return rows


def _load_expansion(path: Path) -> Expansion | None:
    """Parse ``expansion.json`` when present."""
    if not path.is_file():
        return None
    raw = json.loads(path.read_text(encoding="utf-8"))
    entries = [
        ExpandedEntry(
            entry_key=item.get("entry_key", ""),
            title=item.get("title", ""),
            company=item.get("company", ""),
            location=item.get("location", ""),
            start=item.get("start", ""),
            end=item.get("end", ""),
            bullets=list(item.get("bullets", [])),
            char_count=int(item.get("char_count", 0)),
            warnings=list(item.get("warnings", [])),
            on_resume=bool(item.get("on_resume", False)),
        )
        for item in raw.get("entries", [])
    ]
    return Expansion(
        entries=entries,
        warnings=list(raw.get("warnings", [])),
        model=str(raw.get("model", "")),
        char_limit=int(raw.get("char_limit", 0)),
    )


def _load_skills(path: Path) -> list[str]:
    """Extract skill labels from ``skills.json`` when present."""
    if not path.is_file():
        return []
    raw = json.loads(path.read_text(encoding="utf-8"))
    skills = raw.get("skills", [])
    if not isinstance(skills, list):
        return []
    labels: list[str] = []
    for item in skills:
        if isinstance(item, dict) and item.get("skill"):
            labels.append(str(item["skill"]))
        elif isinstance(item, str):
            labels.append(item)
    return labels


def _load_cover_letter(path: Path) -> str:
    """Join cover-letter body paragraphs when ``cover.json`` exists."""
    if not path.is_file():
        return ""
    raw = json.loads(path.read_text(encoding="utf-8"))
    paragraphs = raw.get("paragraphs", [])
    if not isinstance(paragraphs, list):
        return ""
    return "\n\n".join(str(p).strip() for p in paragraphs if str(p).strip())


def _artifact_paths(job_dir: Path) -> dict[str, str]:
    """Collect absolute paths to rendered documents that exist on disk."""
    mapping = {
        "resume_pdf": job_dir / "tailored.pdf",
        "resume_docx": job_dir / "tailored.docx",
        "cover_pdf": job_dir / "cover.pdf",
        "cover_docx": job_dir / "cover.docx",
    }
    return {kind: str(path) for kind, path in mapping.items() if path.is_file()}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def build_packet(
    job_id: str, *, out_dir: Path | None = None,
    applicant_profile: profile_mod.ApplicantProfile | None = None,
) -> packet_models.Packet:
    """Assemble a packet from job artifacts, profile, and master resume."""
    job_dir = out_dir if out_dir is not None else config.OUTPUT_DIR / "jobs" / job_id
    run_path = job_dir / "run.json"
    if not run_path.is_file():
        raise FileNotFoundError(f"run.json not found for job {job_id!r} at {run_path}")

    run = json.loads(run_path.read_text(encoding="utf-8"))
    metadata = run.get("metadata") or {}
    report = run.get("report") or {}

    if applicant_profile is None:
        applicant_profile, _seeded = profile_mod.load_profile()
    resume = load()

    from resume_tailor.apply.funnel import preparation

    expansion_path = job_dir / "expansion.json"
    prepared_expansion = preparation.read_expansion(expansion_path) if expansion_path.is_file() else None
    expansion = prepared_expansion.as_expansion() if prepared_expansion is not None else None
    experience = _experience_from_expansion(expansion.entries) if expansion is not None else []
    artifacts = _artifact_paths(job_dir)
    for kind in ("transcript", "portfolio"):
        uploaded = getattr(applicant_profile, f"{kind}_path")
        if uploaded and Path(uploaded).is_file():
            artifacts[f"{kind}_pdf"] = uploaded
    manifest_artifacts = [packet_models.PreparedArtifact(
        purpose=kind, path=path, filename=Path(path).name,
        mime_type="application/pdf" if kind.endswith("pdf") else
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        sha256=_sha256(Path(path)),
    ) for kind, path in artifacts.items()]
    expansion_status = prepared_expansion.status if prepared_expansion is not None else "missing"
    manifest = packet_models.PreparationManifest(
        preparation_id=_sha256(run_path)[:16], job_id=job_id,
        prepared_at=datetime.fromtimestamp(run_path.stat().st_mtime, timezone.utc).isoformat(),
        source_revision=_sha256(run_path), expansion_status=expansion_status,
        expansion_hash=_sha256(expansion_path) if expansion_path.is_file() else "",
        artifacts=manifest_artifacts,
        preparation_warnings=list(expansion.warnings) if expansion else [],
    )

    ats = str(metadata.get("ats") or "unknown")
    education = packet_fields._build_education(resume)
    fields = packet_fields.build_fields(applicant_profile, resume)
    named = packet_fields.degree_name(education, fields.get("degree_level", ""))
    packet_fields._maybe_set(fields, "degree_name", named or None)
    return packet_models.Packet(
        job_id=job_id,
        built_at=datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        posting_url=str(metadata.get("posting_url") or ""),
        company=str(metadata.get("company") or ""),
        role=str(metadata.get("role") or report.get("title") or ""),
        ats=ats,
        fields=fields,
        education=education,
        experience=experience,
        skills=_load_skills(job_dir / "skills.json"),
        languages=[
            packet_models.PacketLanguage(language=entry.language.strip(), fluent=entry.fluent,
                           levels={k: v for k, v in entry.levels.items() if v.strip()})
            for entry in applicant_profile.languages if entry.language.strip()
        ],
        cover_letter=_load_cover_letter(job_dir / "cover.json"),
        artifacts=artifacts,
        field_hints=ats_hints.hints_for(ats),
        gaps=list(report.get("gaps") or []),
        preparation=manifest,
        inputs_digest=packet_models.inputs_digest(applicant_profile, resume),
    )


#: One writer at a time: on Windows, two threads replacing the same ``packet.json`` at
#: once fail with "Access is denied" (the job thread and a rebuild request can race).
_WRITE_LOCK = threading.Lock()


def _replace(src: Path, dst: Path, attempts: int = 10) -> None:
    """``os.replace``, retried briefly while a reader holds ``dst`` open (Windows)."""
    for attempt in range(attempts):
        try:
            os.replace(src, dst)
            return
        except PermissionError:
            if attempt == attempts - 1:
                raise
            time.sleep(0.05 * (attempt + 1))


def write_packet(job_id: str) -> packet_models.Packet:
    """Build and persist ``packet.json`` for ``job_id``."""
    packet = build_packet(job_id)
    job_dir = config.OUTPUT_DIR / "jobs" / job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    path = job_dir / "packet.json"
    # Temp file + rename: the job is already "succeeded" when this runs, so a reader
    # (the Apply page, the MCP server) can open the file mid-write. An in-place
    # write_text truncates first and was read back as empty JSON. The temp name is
    # unique because the job thread and a rebuild request can write at the same time.
    tmp = path.with_name(f"packet.{uuid.uuid4().hex}.tmp")
    try:
        tmp.write_text(packet.model_dump_json(indent=2) + "\n", encoding="utf-8")
        with _WRITE_LOCK:
            _replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)
    return packet
