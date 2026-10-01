"""ATS identity helpers: URL resolution, canonical keys, and role grouping.

Pure string/HTTP logic — no LLM. Canonical keys identify one requisition;
group keys collapse same-company same-role postings across locations.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

import httpx

from resume_tailor import config

#: Wrapper hosts whose final destination is the real ATS posting URL.
_WRAPPER_HOSTS = frozenset(
    {
        "simplify.jobs",
        "www.simplify.jobs",
        "zapply.jobs",
        "www.zapply.jobs",
        "jobright.ai",
        "www.jobright.ai",
        "lnkd.in",
        "bit.ly",
    }
)

#: Tracking params stripped before caching / keying (``gh_jid`` is kept).
_STRIP_QUERY = frozenset({"s", "gh_src"})

_GH_PATH = re.compile(r"/(?P<board>[^/]+)/jobs/(?P<id>\d+)", re.I)
_LEVER = re.compile(
    r"jobs\.lever\.co/(?P<co>[^/]+)/(?P<id>[0-9a-f-]{36})", re.I
)
_ASHBY = re.compile(
    r"jobs\.ashbyhq\.com/(?P<co>[^/]+)/(?P<id>[0-9a-f-]{36})", re.I
)
_SMART = re.compile(
    r"jobs\.smartrecruiters\.com/(?P<co>[^/]+)/(?P<id>\d+)", re.I
)
_ICIMS = re.compile(r"(?P<co>[^.]+)\.icims\.com/jobs/(?P<id>\d+)", re.I)
_ORACLE = re.compile(r"/hcmUI/CandidateExperience/.*/job/(?P<id>\d+)", re.I)
_JOBVITE = re.compile(r"jobs\.jobvite\.com/(?P<co>[^/]+)/job/(?P<id>[A-Za-z0-9]+)", re.I)
_BAMBOO = re.compile(r"/careers/(?P<id>\d+)", re.I)
_LINKEDIN = re.compile(r"/jobs/view/(?:[^/]*?-)?(?P<id>\d+)", re.I)
_HANDSHAKE = re.compile(r"/(?:stu/)?jobs/(?P<id>\d+)", re.I)
#: The requisition id is everything after the last ``_`` in Workday's final path
#: segment (``…Intern-2027_R39474`` -> ``R39474``); require a digit so a plain
#: word segment (no ``_id`` suffix) falls through to `_WORKDAY_FALLBACK`.
_WORKDAY_TAIL_ID = re.compile(r"_(?P<id>[^_/]*\d[^_/]*)$")
_WORKDAY_FALLBACK = re.compile(r"_?(?:R|JR)\d{4,}", re.I)

_CORP_SUFFIX = re.compile(
    r"\b(inc|llc|corp|corporation|ltd|co)\.?$", re.I
)
_PUNCT = re.compile(r"[^\w\s]", re.UNICODE)
_YEAR = re.compile(r"\b20\d{2}\b")
_SEASON = re.compile(
    r"\b(summer|fall|spring|winter|autumn)\b", re.I
)
_REQ_ID = re.compile(r"\b[A-Z]{1,3}[-_]?\d{4,}\b")
_PAREN = re.compile(r"\([^)]*\)")
_STATE_ABBR = re.compile(r"\b[A-Z]{2}\b")


def _cache_path() -> Path:
    """Permanent resolve-cache file under the applications output tree."""
    return config.APPLICATIONS_OUTPUT_DIR / "url_resolve_cache.json"


def _load_cache() -> dict[str, str]:
    """Load the wrapper → final URL map, or an empty dict when missing."""
    path = _cache_path()
    if not path.is_file():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(raw, dict):
        return {}
    return {str(k): str(v) for k, v in raw.items()}


def _save_cache(cache: dict[str, str]) -> None:
    """Atomically write the resolve cache."""
    path = _cache_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(cache, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(path)


def _strip_tracking(url: str) -> str:
    """Drop ``utm_*``, ``s``, and ``gh_src`` query params; keep ``gh_jid``."""
    parsed = urlparse(url)
    if not parsed.query:
        return url
    kept: list[tuple[str, str]] = []
    for key, values in parse_qs(parsed.query, keep_blank_values=True).items():
        if key.lower().startswith("utm_") or key.lower() in _STRIP_QUERY:
            continue
        for value in values:
            kept.append((key, value))
    query = urlencode(kept)
    return urlunparse(parsed._replace(query=query))


def resolve_final_url(url: str, *, timeout: float = 10.0) -> str:
    """Follow wrapper redirects to the ATS posting URL, caching permanently.

    Non-wrapper hosts return ``url`` unchanged. On HTTP errors the original
    ``url`` is returned and nothing is written to the cache.
    """
    if not url:
        return url
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if host not in _WRAPPER_HOSTS:
        return url

    cache = _load_cache()
    if url in cache:
        return cache[url]

    try:
        response = httpx.head(url, follow_redirects=True, timeout=timeout)
        if response.status_code == 405:
            response = httpx.get(url, follow_redirects=True, timeout=timeout)
        final = str(response.url)
    except Exception:  # noqa: BLE001 — network failures fall back to the wrapper
        return url

    final = _strip_tracking(final)
    cache[url] = final
    _save_cache(cache)
    return final


def canonical_key(final_url: str) -> str:
    """Derive a stable ``ats:slug:id`` key from a posting URL. Never returns None."""
    if not final_url:
        return "other:unknown:empty"
    parsed = urlparse(final_url)
    host = (parsed.hostname or "").lower()
    path = parsed.path or ""
    query = parse_qs(parsed.query)

    if "greenhouse.io" in host:
        match = _GH_PATH.search(path)
        if match:
            return f"greenhouse:{match.group('board').lower()}:{match.group('id')}"

    # Embedded Greenhouse job id on third-party boards (Careerpuck, etc.).
    jid = (query.get("gh_jid") or [None])[0]
    if jid and str(jid).isdigit():
        segments = [s for s in path.split("/") if s]
        board = "unknown"
        if "job-board" in segments:
            idx = segments.index("job-board")
            if idx + 1 < len(segments):
                board = segments[idx + 1]
        elif segments:
            board = segments[0]
        return f"greenhouse:{board.lower()}:{jid}"

    lever = _LEVER.search(final_url)
    if lever:
        return f"lever:{lever.group('co').lower()}:{lever.group('id').lower()}"

    ashby = _ASHBY.search(final_url)
    if ashby:
        return f"ashby:{ashby.group('co').lower()}:{ashby.group('id').lower()}"

    if "myworkdayjobs.com" in host:
        tenant = host.split(".")[0]
        last_segment = path.rstrip("/").rsplit("/", 1)[-1]
        match = _WORKDAY_TAIL_ID.search(last_segment)
        if match:
            return f"workday:{tenant.lower()}:{match.group('id').upper()}"
        fallback = _WORKDAY_FALLBACK.search(path)
        if fallback:
            return f"workday:{tenant.lower()}:{fallback.group(0).upper()}"

    smart = _SMART.search(final_url)
    if smart:
        return (
            f"smartrecruiters:{smart.group('co').lower()}:{smart.group('id')}"
        )

    icims = _ICIMS.search(final_url)
    if icims:
        return f"icims:{icims.group('co').lower()}:{icims.group('id')}"

    tenant = host.split(".")[0]

    def first(name: str) -> str:
        return (query.get(name) or [""])[0].strip()

    if host.endswith("taleo.net") and first("job"):
        return f"taleo:{tenant}:{first('job').lower()}"
    if "successfactors" in host and first("career_job_req_id"):
        company = first("company").lower() or tenant
        return f"successfactors:{company}:{first('career_job_req_id')}"
    oracle = _ORACLE.search(path) if "oraclecloud.com" in host else None
    if oracle:
        return f"oracle:{tenant}:{oracle.group('id')}"
    jobvite = _JOBVITE.search(final_url)
    if jobvite:
        return f"jobvite:{jobvite.group('co').lower()}:{jobvite.group('id')}"
    if host.endswith("bamboohr.com"):
        bamboo = _BAMBOO.search(path)
        job = bamboo.group("id") if bamboo else first("id")
        if job.isdigit():
            return f"bamboohr:{tenant}:{job}"
    # Job boards: one global id space, so the slug is the board itself. A search or
    # collections page names the job open in its detail pane by query parameter
    # (LinkedIn ``currentJobId``, Indeed ``vjk``), so that page keys as the job itself.
    if host == "linkedin.com" or host.endswith(".linkedin.com"):
        linkedin = _LINKEDIN.search(path)
        job = linkedin.group("id") if linkedin else first("currentJobId")
        if job.isdigit():
            return f"linkedin:jobs:{job}"
    if host == "indeed.com" or host.endswith(".indeed.com"):
        job = first("jk") or first("vjk")
        if job:
            return f"indeed:jobs:{job.lower()}"
    if host.endswith("joinhandshake.com"):
        handshake = _HANDSHAKE.search(path)
        if handshake:
            return f"handshake:jobs:{handshake.group('id')}"

    digest = hashlib.sha1(path.encode("utf-8")).hexdigest()[:12]
    return f"other:{host}:{digest}"


def normalize_company(text: str) -> str:
    """Casefold, strip punctuation, and drop trailing corporate suffixes."""
    cleaned = _PUNCT.sub(" ", text.casefold())
    cleaned = _CORP_SUFFIX.sub("", cleaned.strip())
    return re.sub(r"\s+", " ", cleaned).strip()


def normalize_role(text: str) -> str:
    """Strip years, seasons, req ids, location segments, and parentheticals."""
    # Req ids before casefold so the [A-Z] pattern still matches.
    cleaned = _REQ_ID.sub(" ", text)
    cleaned = _PAREN.sub(" ", cleaned)
    cleaned = _YEAR.sub(" ", cleaned)
    cleaned = _SEASON.sub(" ", cleaned)

    # Split on dash/pipe and drop location-like segments (pre-casefold state check).
    parts = re.split(r"\s+[-–|]\s+", cleaned)
    kept: list[str] = []
    for part in parts:
        if "," in part:
            continue
        if re.search(r"\bremote\b", part, re.I):
            continue
        if _STATE_ABBR.search(part):
            continue
        kept.append(part)
    cleaned = " ".join(kept) if kept else cleaned
    cleaned = cleaned.casefold()
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


def group_key(company: str, role: str) -> str:
    """Stable key for same-company same-role postings across locations."""
    return f"{normalize_company(company)}|{normalize_role(role)}"
