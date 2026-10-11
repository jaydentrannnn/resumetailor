"""Your own cover letter: the starter download, the upload and its removal."""

from __future__ import annotations

from resume_tailor import config
from resume_tailor.content import data
from resume_tailor.document import cover_own, cover_settings, cover_template, docx_normalize
from resume_tailor.document.cover_settings import CoverSettings
from resume_tailor.document.template_profile import load_profile

from . import template_ops

STARTER_NAME = "cover-letter-starter.docx"


class OwnLetterError(template_ops.TemplateValidationError):
    """An uploaded letter that can't be used; `problems` says why, one line each."""

    def __init__(self, problems: list[str]) -> None:
        super().__init__(" ".join(problems))
        self.problems = problems


def starter() -> bytes:
    """The letter built from the current template, with «fields» for every value."""
    profile = load_profile()
    if profile is None or not config.BASELINE_TEMPLATE_PATH.exists():
        raise FileNotFoundError("No resume template is installed yet.")
    try:
        resume = data.load()
    except (FileNotFoundError, ValueError):
        resume = None
    directory = config.CACHE_DIR / "cover_preview"
    template = cover_template.ensure_cover_template(
        dst=directory / "cover_generated.docx",
        meta_path=directory / "cover_generated.meta.json",
        profile=profile,
        settings=CoverSettings(),
    )
    return cover_own.starter_letter(template, profile, resume)


def upload(raw: bytes, filename: str) -> CoverSettings:
    """Check and store an own letter, and switch the profile to it. Caller holds LOCK."""
    try:
        prepared = docx_normalize.prepare(raw, filename)
    except docx_normalize.UploadFormatError as exc:
        raise OwnLetterError([str(exc)]) from exc
    problems = cover_own.check(prepared.raw)
    if problems:
        raise OwnLetterError(problems)
    config.COVER_OWN_PATH.parent.mkdir(parents=True, exist_ok=True)
    config.COVER_OWN_PATH.write_bytes(prepared.raw)
    settings = cover_settings.load().model_copy(update={"design": "own"})
    cover_settings.save(settings)
    return settings


def remove() -> CoverSettings:
    """Delete the own letter and go back to the generated one. Caller holds LOCK."""
    config.COVER_OWN_PATH.unlink(missing_ok=True)
    settings = cover_settings.load().model_copy(update={"design": "generated"})
    cover_settings.save(settings)
    return settings
