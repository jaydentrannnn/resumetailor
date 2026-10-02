"""Edit a finished run's bullets and render again, with no model call (Tailor page, T4).

A run saves exactly what its final render used (`save_snapshot`): the resume after
exclusions and facet selection, the template file, the template layout, contact
fields and merges. The template is stored once per content hash in
``<OUTPUT_DIR>/run_templates/`` and the snapshot records the hash: every run on the
same template shares one file (a template embeds its fonts, ~750 KB). Runs made
before that keep their own ``template.docx`` until housekeeping moves it into the store. A re-render replays `render.render` with the student's edits on
top of the AI's bullets, so the document keeps the run's template even if the live
template has changed since.

Rules, mirroring the pipeline's own:
- Nothing is invented by code. Text is the AI's rewrite, the master resume's source
  text ("use original"), or what the student typed. Typed text goes through the
  fabrication guard for warnings only (it is the student's own claim), and each
  flagged bullet needs an explicit "this is accurate" before it renders.
- Nothing is truncated. A result over the page target is not saved; the caller is
  told how many lines over it is.
- The AI's version is kept (`*.v1.*`) the first time an edit is saved, so "Reset to
  AI version" always has something to go back to.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from resume_tailor import config
from resume_tailor.content.data import Bullet, Experience, MasterResume
from resume_tailor.document import render
from resume_tailor.pipeline.merge import MergeGroup

SNAPSHOT = "render_snapshot.json"
TEMPLATE = "template.docx"
TEMPLATE_STORE = "run_templates"
MAX_BULLET_CHARS = 1000


class RerenderError(ValueError):
    """The request cannot be applied (unknown bullet, empty text, no snapshot)."""


class NoSnapshot(RerenderError):
    """The run predates re-render support."""


def save_snapshot(
    out_dir: Path,
    resume: MasterResume,
    *,
    target_pages: int,
    include_project_links: bool,
    contact_fields: list[str] | None,
    layout: dict,
    merges: list[MergeGroup],
    template: Path | None = None,
    fill_target: float | None = None,
    lines_per_page: int | None = None,
) -> None:
    """Record the final render's inputs beside the run's other artifacts."""
    template = template or config.DEFAULT_TEMPLATE_PATH
    sha = store_template(out_dir, template.read_bytes())
    payload = {
        "version": 1,
        "template_sha": sha,
        "resume": resume.model_dump(mode="json", by_alias=True),
        "target_pages": target_pages,
        "fill_target": fill_target,
        "lines_per_page": lines_per_page,
        "include_project_links": include_project_links,
        "contact_fields": list(contact_fields) if contact_fields is not None else None,
        "layout": layout,
        "merges": [
            {"survivor": g.survivor_id, "members": list(g.member_ids)} for g in merges
        ],
    }
    (out_dir / SNAPSHOT).write_text(json.dumps(payload, indent=2, default=list), "utf-8")


def template_store(out_dir: Path) -> Path:
    """The shared template store for a run folder (``<OUTPUT_DIR>/jobs/<id>``)."""
    return out_dir.parent.parent / TEMPLATE_STORE


def store_template(out_dir: Path, raw: bytes) -> str:
    """Put ``raw`` in the store (once per content) and return its hash.

    An existing copy is touched so housekeeping's grace period, which protects a file
    whose snapshot is still being written, starts from this run.
    """
    sha = hashlib.sha256(raw).hexdigest()
    store = template_store(out_dir)
    store.mkdir(parents=True, exist_ok=True)
    target = store / f"{sha}.docx"
    if target.is_file():
        os.utime(target)
    else:
        partial = target.with_suffix(f".{os.getpid()}.partial")
        partial.write_bytes(raw)
        partial.replace(target)
    return sha


def template_for(out_dir: Path, snapshot: dict) -> Path | None:
    """The run's template file: its own legacy copy, else the stored one."""
    legacy = out_dir / TEMPLATE
    if legacy.is_file():
        return legacy
    sha = snapshot.get("template_sha")
    if isinstance(sha, str) and sha:
        stored = template_store(out_dir) / f"{sha}.docx"
        if stored.is_file():
            return stored
    return None


@dataclass
class _Run:
    out_dir: Path
    template: Path
    snapshot: dict
    resume: MasterResume
    ai: dict[str, str]
    current: dict[str, str]
    sources: dict[str, Bullet]
    merged_from: dict[str, list[str]] = field(default_factory=dict)


def _load(out_dir: Path) -> _Run:
    snap_path = out_dir / SNAPSHOT
    snapshot = json.loads(snap_path.read_text("utf-8")) if snap_path.is_file() else None
    template = template_for(out_dir, snapshot) if snapshot is not None else None
    if snapshot is None or template is None:
        raise NoSnapshot(
            "Editing is available for runs made after this feature was added. "
            "Tailor again to edit bullets."
        )
    resume = MasterResume.model_validate(snapshot["resume"])
    current = json.loads((out_dir / "bullets.json").read_text("utf-8"))
    v1 = out_dir / "bullets.v1.json"
    ai = json.loads(v1.read_text("utf-8")) if v1.is_file() else dict(current)
    sources = {b.id: b for b in resume.all_bullets()}
    merged_from = {m["survivor"]: list(m["members"]) for m in snapshot.get("merges", [])}
    return _Run(out_dir, template, snapshot, resume, ai, current, sources, merged_from)


def bullet_rows(out_dir: Path) -> list[dict]:
    """Every bullet the AI version rendered, in document order, with its source text."""
    run = _load(out_dir)
    rows: list[dict] = []
    for section in run.resume.entry_sections:
        for entry in section.entries:
            label = (
                " · ".join(p for p in (entry.title, entry.company) if p)
                if isinstance(entry, Experience)
                else entry.name
            )
            for bullet in entry.bullets:
                if bullet.id not in run.ai:
                    continue
                members = run.merged_from.get(bullet.id, [])
                source = (
                    " / ".join(run.sources[m].text for m in members if m in run.sources)
                    if members
                    else bullet.text
                )
                rows.append({
                    "bullet_id": bullet.id,
                    "section_title": section.title,
                    "entry_label": label,
                    "source_text": source,
                    "ai_text": run.ai[bullet.id],
                    "current_text": run.current.get(bullet.id),
                    "merged_from": members,
                })
    return rows


def _check(run: _Run, bullet_id: str, text: str) -> list[str]:
    from resume_tailor.pipeline import fabrication

    members = run.merged_from.get(bullet_id) or [bullet_id]
    sources = [run.sources[m] for m in members if m in run.sources]
    return fabrication._check_fabrication(sources, text) if sources else []


def _apply(
    run: _Run, edits: dict[str, str], reverted: list[str], removed: list[str]
) -> tuple[dict[str, str], dict[str, list[str]]]:
    """The requested bullets relative to the AI version, plus guard flags on edits."""
    unknown = sorted(b for b in {*edits, *reverted, *removed} if b not in run.ai)
    if unknown:
        raise RerenderError(f"Unknown bullet(s) for this run: {', '.join(unknown)}")
    bullets = dict(run.ai)
    for bullet_id in removed:
        bullets.pop(bullet_id, None)
    for bullet_id in reverted:
        if bullet_id in removed:
            continue
        members = run.merged_from.get(bullet_id)
        if members:
            # "Use original" on a merged bullet restores every bullet it absorbed.
            bullets.pop(bullet_id, None)
            for m in members:
                if m in run.sources:
                    bullets[m] = run.sources[m].text
        else:
            bullets[bullet_id] = run.sources[bullet_id].text
    flagged: dict[str, list[str]] = {}
    for bullet_id, raw in edits.items():
        if bullet_id in removed or bullet_id in reverted:
            continue
        text = " ".join(raw.split())
        if not text:
            raise RerenderError("An edited bullet is empty; remove it instead.")
        if len(text) > MAX_BULLET_CHARS:
            raise RerenderError(f"An edited bullet is over {MAX_BULLET_CHARS} characters.")
        bullets[bullet_id] = text
        terms = _check(run, bullet_id, text)
        if terms:
            flagged[bullet_id] = terms
    if not bullets:
        raise RerenderError("Every bullet was removed; keep at least one.")
    return bullets, flagged


def rerender(
    out_dir: Path,
    *,
    edits: dict[str, str],
    reverted: list[str],
    removed: list[str],
    confirmed: list[str],
) -> dict:
    """Render the edited bullets. Saves only when every flag is confirmed and it fits.

    Returns ``{"status": "needs_confirmation" | "over" | "saved", ...}``.
    """
    run = _load(out_dir)
    bullets, flagged = _apply(run, edits, reverted, removed)
    unconfirmed = {b: t for b, t in flagged.items() if b not in set(confirmed)}
    if unconfirmed:
        return {"status": "needs_confirmation", "flagged": unconfirmed}

    target = int(run.snapshot["target_pages"])
    lines_per_page = run.snapshot.get("lines_per_page") or config.LINES_PER_PAGE
    tmp_docx = out_dir / "rerender.tmp.docx"
    tmp_pdf = tmp_docx.with_suffix(".pdf")
    warnings: list[str] = []
    try:
        render.render(
            run.resume,
            bullets=bullets,
            template=run.template,
            out=tmp_docx,
            include_project_links=run.snapshot["include_project_links"],
            contact_fields=run.snapshot["contact_fields"],
            layout=run.snapshot["layout"],
        )
        try:
            pages, lines = render.measure_detail(tmp_docx)
            estimated = False
        except RuntimeError as exc:
            from resume_tailor.pipeline import fit_lines

            lines = fit_lines.estimate_lines(run.resume, bullets)
            pages = math.ceil(lines / lines_per_page)
            estimated = True
            warnings.append(f"PDF engine unavailable, so the page count is an estimate ({exc}).")
        if pages > target:
            over = max(1, lines - target * lines_per_page)
            return {"status": "over", "pages": pages, "target_pages": target, "over_by_lines": over}

        for name in ("tailored.docx", "tailored.pdf", "bullets.json"):
            original = out_dir / name
            backup = out_dir / name.replace(".", ".v1.", 1)
            if original.is_file() and not backup.exists():
                shutil.copy2(original, backup)
        tmp_docx.replace(out_dir / "tailored.docx")
        if tmp_pdf.is_file():
            tmp_pdf.replace(out_dir / "tailored.pdf")
        elif estimated:
            (out_dir / "tailored.pdf").unlink(missing_ok=True)  # never serve a stale PDF
        (out_dir / "bullets.json").write_text(json.dumps(bullets, indent=2), "utf-8")
        (out_dir / "review.json").write_text(
            json.dumps(
                {"edits": edits, "reverted": reverted, "removed": removed, "confirmed": confirmed},
                indent=2,
            ),
            "utf-8",
        )
        from resume_tailor.pipeline import resume_quality

        capacity = target * lines_per_page
        quality = resume_quality.assess(
            run.resume, bullets, run.snapshot["layout"], fill_ratio=lines / capacity,
            fill_target=run.snapshot.get("fill_target"), estimated=estimated,
        )
        quality.verified = (
            run.snapshot.get("fill_target") is not None
            and run.snapshot.get("lines_per_page") is not None
        )
        resume_quality.save(out_dir, quality)
        return {
            "status": "saved",
            "pages": pages,
            "pages_are_estimated": estimated,
            "warnings": warnings,
            "flagged": flagged,
            "quality": quality.model_dump(),
        }
    finally:
        tmp_docx.unlink(missing_ok=True)
        tmp_pdf.unlink(missing_ok=True)
