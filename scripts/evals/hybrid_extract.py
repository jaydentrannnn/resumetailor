"""Experiment E: dictionary candidates + one labelling call, vs `jd.extract` alone.

1. A dictionary of skill phrases: the vocabulary library (terms and aliases), the
   resume's own skills, and every phrase/canonical from the OTHER saved extractions
   (leave-one-out, so a posting never finds the terms its own extraction produced).
2. A word-boundary scan of the posting returns the phrases it contains, in the
   posting's own spelling. No model call.
3. One call to the extract model with `jd.extract`'s exact system prompt and user
   message, plus the candidates: keep the real requirements, label them, add misses.

The only difference from the current method is the candidate list, so a gap between
the arms measures the dictionary and nothing else. Output is a `JobRequirements`
post-processed exactly like `jd.extract` (canonical tags, evidence cap); non-verbatim
phrases are left in so both arms are scored by the same `verify_verbatim` metric.
"""

from __future__ import annotations

import functools
import re
from collections import defaultdict
from collections.abc import Iterable

from resume_tailor import config
from resume_tailor.content import industries
from resume_tailor.infra import llm
from resume_tailor.pipeline import jd
from resume_tailor.pipeline.jd import JobRequirements

#: Phrases this short (or "go") only count when the posting capitalises them: "R",
#: "C", "Go" are languages; "r", "c", "go" are letters and a verb.
_SHORT = 2
_CASE_SENSITIVE = {"go"}
MAX_CANDIDATES = 80

_HINT = (
    "<dictionary_candidates> lists skill terms a dictionary lookup found verbatim in the "
    "posting. Use it as a starting list: keep only the terms this posting treats as real "
    "requirements of the role (copy `phrase` exactly as it appears in the posting), drop "
    "the rest, and add any requirement the list missed."
)


def _norm(text: str) -> str:
    return " ".join(text.lower().split())


class Dictionary:
    """Phrase -> canonical, remembering which saved postings contributed each phrase."""

    def __init__(self, base_terms: Iterable[str] = (), aliases: dict[str, str] | None = None):
        self.canonical: dict[str, str] = {}
        self._sources: dict[str, set[str]] = defaultdict(set)
        self._base: set[str] = set()
        for term in base_terms:
            self._add_base(term, term)
        for alias, canonical in (aliases or {}).items():
            self._add_base(alias, canonical)
            self._add_base(canonical, canonical)

    def _add_base(self, phrase: str, canonical: str) -> None:
        key = _norm(phrase)
        if key:
            self._base.add(key)
            self.canonical.setdefault(key, canonical)

    def add_extraction(self, source_id: str, requirements: JobRequirements) -> None:
        for kw in requirements.keywords:
            for phrase in (kw.phrase, kw.canonical):
                key = _norm(phrase)
                if key:
                    self._sources[key].add(source_id)
                    self.canonical.setdefault(key, kw.canonical)

    def phrases(self, *, excluding: str | None = None) -> list[str]:
        """Every phrase, minus those only `excluding` contributed (leave-one-out)."""
        return [p for p in self.canonical
                if p in self._base or (self._sources.get(p, set()) - {excluding})]


@functools.cache
def _pattern(phrase: str) -> re.Pattern[str]:
    if phrase in _CASE_SENSITIVE:
        body, flags = re.escape(phrase.capitalize()), 0  # "Go", not the verb
    elif len(phrase) <= _SHORT:
        body, flags = re.escape(phrase.upper()), 0  # "R", "C#", "ML", "QA"
    else:
        body, flags = r"\s+".join(re.escape(w) for w in phrase.split()), re.I
    return re.compile(rf"(?<![\w+#]){body}(?![\w+#])", flags)


def candidates(jd_text: str, phrases: Iterable[str]) -> list[tuple[str, str]]:
    """`(surface, phrase)` for each dictionary phrase in the posting, in posting order.

    Longest match first; a phrase inside an already-matched span ("learning" inside
    "machine learning") is dropped.
    """
    lowered = jd_text.lower()
    hits: list[tuple[int, int, str, str]] = []
    for phrase in sorted(set(phrases), key=len, reverse=True):
        if phrase.split()[0] not in lowered:
            continue  # cheap prefilter before the regex
        for match in _pattern(phrase).finditer(jd_text):
            start, end = match.span()
            if not any(s <= start and end <= e for s, e, _, _ in hits):
                hits.append((start, end, match.group(0), phrase))
                break
    hits.sort()
    return [(surface, phrase) for _, _, surface, phrase in hits[:MAX_CANDIDATES]]


def user_message(jd_text: str, known_tags: list[str] | None,
                 found: list[tuple[str, str]], canonical: dict[str, str]) -> str:
    listed = "\n".join(f"- {surface} ({canonical.get(phrase, phrase)})"
                       for surface, phrase in found) or "(none found)"
    return (jd._build_user_message(jd_text, known_tags)
            + f"\n\n<dictionary_candidates>\n{listed}\n</dictionary_candidates>\n\n{_HINT}")


def extract(
    jd_text: str, dictionary: Dictionary, *, known_tags: list[str] | None,
    exclude: str | None = None,
) -> tuple[JobRequirements, int]:
    """The hybrid extraction and how many dictionary candidates it was given."""
    found = candidates(jd_text, dictionary.phrases(excluding=exclude))
    client = llm.client_for("extract")
    response = client.messages.parse(
        model=config.model_for("extract"),
        max_tokens=config.max_tokens_for("extract"),
        system=industries.system("extract", jd._SYSTEM),
        messages=[{"role": "user", "content": user_message(
            jd_text.strip(), known_tags, found, dictionary.canonical)}],
        output_format=JobRequirements,
        output_config={"effort": config.effort_for("extract")},
    )
    requirements = response.parsed_output
    if requirements is None:
        raise RuntimeError(f"no parseable requirements (stop_reason={response.stop_reason!r})")
    for kw in requirements.keywords:
        kw.canonical = config.canonical_tag(kw.canonical)
        jd._apply_evidence_cap(kw)
    return requirements, len(found)
