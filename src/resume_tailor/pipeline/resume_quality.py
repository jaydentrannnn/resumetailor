"""Deterministic quality of the accepted resume, with no model or document XML."""

from __future__ import annotations

import json
import os
from pathlib import Path

from pydantic import BaseModel, Field

from resume_tailor import config
from resume_tailor.content.data import MasterResume


class MissingSection(BaseModel):
    id: str
    title: str
    reason: str


class ResumeQuality(BaseModel):
    fill_ratio: float | None = None
    fill_target: float | None = None
    estimated: bool = False
    missing_sections: list[MissingSection] = Field(default_factory=list)
    verified: bool = True

    @property
    def warnings(self) -> list[str]:
        result = []
        if not self.verified:
            result.append(
                "Resume quality could not be verified. Prepare this resume again before Fill."
            )
        if (
            self.fill_ratio is not None
            and self.fill_target is not None
            and self.fill_ratio < self.fill_target
        ):
            prefix = "Estimated page fill" if self.estimated else "Page fill"
            result.append(f"{prefix} is {self.fill_ratio:.0%}; target is {self.fill_target:.0%}.")
        for section in self.missing_sections:
            result.append(f"{section.title} is missing: {section.reason}.")
        return result


def assess(
    resume: MasterResume,
    bullets: dict[str, str],
    layout: dict,
    *,
    fill_ratio: float | None,
    fill_target: float | None,
    estimated: bool = False,
) -> ResumeQuality:
    enabled = layout.get("enabled") or {}
    missing = []
    for section in resume.sections:
        if not section.entries:
            continue  # Includes sections whose entries were intentionally excluded.
        key = config.SECTION_KIND_ENABLED_KEY[section.kind]
        if not enabled.get(key, config.SECTION_KIND_ENABLED_DEFAULT[section.kind]):
            reason = "this template does not support the selected section"
        elif section.kind in {"experience", "project"} and not any(
            b.id in bullets for entry in section.entries for b in entry.bullets
        ):
            reason = "no entries remained in the final page-fit selection"
        else:
            continue
        missing.append(MissingSection(id=section.id, title=section.title, reason=reason))
    return ResumeQuality(
        fill_ratio=fill_ratio,
        fill_target=fill_target,
        estimated=estimated,
        missing_sections=missing,
    )


def save(out_dir: Path, quality: ResumeQuality) -> None:
    path = out_dir / "quality.json"
    partial = path.with_suffix(".partial")
    partial.write_text(quality.model_dump_json(indent=2), "utf-8")
    os.replace(partial, path)


def read(out_dir: Path) -> ResumeQuality:
    """Old runs need enough saved evidence; current profile values are never evidence."""
    try:
        if (out_dir / "quality.json").exists():
            return ResumeQuality.model_validate_json((out_dir / "quality.json").read_text("utf-8"))
        record = json.loads((out_dir / "run.json").read_text("utf-8"))
        report = record.get("report") or {}
        if report.get("quality"):
            return ResumeQuality.model_validate(report["quality"])
        # Manual edits before quality metadata existed cannot reuse the original fit.
        if (out_dir / "review.json").exists():
            return ResumeQuality(verified=False)
        snapshot = json.loads((out_dir / "render_snapshot.json").read_text("utf-8"))
        bullets = json.loads((out_dir / "bullets.json").read_text("utf-8"))
        trace = report.get("fit_trace") or []
        target = (record.get("settings") or {}).get("fill_target")
        if not trace or target is None or trace[-1].get("bullets") != len(bullets):
            return ResumeQuality(verified=False)
        return assess(
            MasterResume.model_validate(snapshot["resume"]),
            bullets,
            snapshot["layout"],
            fill_ratio=trace[-1]["fill"],
            fill_target=target,
            estimated=bool(report.get("pages_are_estimated")),
        )
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return ResumeQuality(verified=False)
