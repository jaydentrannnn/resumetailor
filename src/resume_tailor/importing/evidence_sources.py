"""Evidence sources from what the student adds: GitHub repositories, pasted text, files.

Every text is cleaned by `posting_guard.guard` (hidden characters removed, lines aimed
at an AI flagged) and capped at `research.pages.MAX_CHARS`. Files are read with the
posting upload's extractors (`jd_input`'s .txt, .pdf and .docx readers), under this
module's own limits: a short letter is fine here, where a posting that short is not.
No LLM; the only network reads are GitHub's, in `github_evidence`.
"""

from __future__ import annotations

import hashlib
from pathlib import PurePath

from resume_tailor.content.evidence_store import EvidenceSource, SourceKind, now, short_id
from resume_tailor.pipeline import jd_input
from resume_tailor.research import pages

from .github_evidence import Repo, guard_flags, repo_text

MAX_FILE_BYTES = 5 * 1024 * 1024
MIN_CHARS = 40
FILE_TYPES = (".txt", ".pdf", ".docx")


class SourceError(ValueError):
    """Plain-words reason a text could not become a source."""


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def from_repo(repo: Repo) -> EvidenceSource:
    text = repo_text(repo)
    return EvidenceSource(
        id=short_id("s", "github", repo.full_name.casefold()),
        kind="github",
        title=repo.full_name,
        url=repo.url,
        added_at=now(),
        sha=_sha(text),
        text=text,
        flags=repo.flags,
        attribution=repo.attribution,
        commit_share=repo.commit_share,
        languages=repo.languages,
    )


def from_text(kind: SourceKind, title: str, text: str) -> EvidenceSource:
    """A pasted syllabus, reference letter or write-up."""
    cleaned, findings = pages.clean(text)
    if len(cleaned) < MIN_CHARS:
        raise SourceError("That text is too short to read anything from.")
    title = " ".join(title.split())[:120] or {
        "syllabus": "Course syllabus", "letter": "Reference letter",
        "writeup": "Project write-up",
    }.get(kind, "Document")
    sha = _sha(cleaned)
    return EvidenceSource(
        id=short_id("s", kind, sha), kind=kind, title=title, added_at=now(), sha=sha,
        text=cleaned, flags=guard_flags(findings),
    )


def from_file(kind: SourceKind, title: str, filename: str, raw: bytes) -> EvidenceSource:
    """An uploaded .txt, .pdf or .docx."""
    if PurePath(filename or "").suffix.lower() not in FILE_TYPES:
        raise SourceError("Upload a .txt, .pdf or .docx file, or paste the text.")
    if len(raw) > MAX_FILE_BYTES:
        raise SourceError("That file is over 5 MB; paste the part that matters instead.")
    suffix = PurePath(filename).suffix.lower()
    try:
        if suffix == ".pdf":
            text = jd_input._pdf_text(raw)
        elif suffix == ".docx":
            text = jd_input._docx_text(raw)
        else:
            text = jd_input._decode(raw)
    except jd_input.JdInputError as exc:
        raise SourceError(str(exc).replace(" the description", " the text")) from None
    try:
        return from_text(kind, title or PurePath(filename).stem, text)
    except SourceError:
        raise SourceError("Too little text was found in that file to read anything from.") from None
