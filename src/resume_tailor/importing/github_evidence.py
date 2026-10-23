"""A student's GitHub repositories as evidence sources. Reads only, through the polite fetcher.

For a username: the repositories they own, most recently pushed first, at most
`MAX_REPOS`. For a repository link: that one repository. Each becomes a source whose
text is its name, description, languages and README (`repo_text`).

Each repository is labelled with whose work it is (`attribution`), from GitHub's
contributor counts: ``own`` when the student made at least `OWN_SHARE` of its commits,
``contributed`` below that, ``fork`` for a fork (shown, never proposed as their work),
``unknown`` when GitHub did not count the student at all (commits under an email the
account does not list, say).

Without a token GitHub allows 60 API reads an hour; one repository costs three (details
or the list entry, languages, contributors; READMEs come from raw.githubusercontent.com).
An optional ``GITHUB_TOKEN`` raises that and is sent to api.github.com only.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from urllib.parse import quote

from resume_tailor import config
from resume_tailor.apply.discovery.sources import raw_readme_url
from resume_tailor.content.evidence_store import Attribution
from resume_tailor.infra.polite_fetch import Fetcher, FetchError
from resume_tailor.pipeline import posting_guard
from resume_tailor.research import pages

API = "https://api.github.com"
MAX_REPOS = 20
OWN_SHARE = 0.8
#: README names tried in order on raw.githubusercontent.com (case matters there).
_READMES = ("README.md", "readme.md", "Readme.md", "README.rst", "README")

_NAME = r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})"
_USER = re.compile(rf"^@?({_NAME})$")
_URL = re.compile(
    rf"^(?:https?://)?(?:www\.)?github\.com/({_NAME})(?:/([A-Za-z0-9._-]+?))?(?:\.git)?(?:[/#?].*)?$",
    re.IGNORECASE,
)
_IMAGE = re.compile(r"!\[[^\]]*\]\([^)]*\)")
_LINK = re.compile(r"\[([^\]]*)\]\([^)]*\)")
_FENCE = re.compile(r"^(```|~~~).*?^\1", re.DOTALL | re.MULTILINE)
_TAG = re.compile(r"<[^>]+>")


class GitHubError(Exception):
    """Plain-words reason the repositories could not be read."""


@dataclass
class Repo:
    owner: str
    name: str
    url: str
    description: str = ""
    fork: bool = False
    languages: list[str] = field(default_factory=list)
    readme: str = ""
    attribution: Attribution = "unknown"
    commit_share: float | None = None
    pushed_at: str = ""
    flags: list[str] = field(default_factory=list)

    @property
    def full_name(self) -> str:
        return f"{self.owner}/{self.name}"


def parse_target(text: str) -> tuple[str, str | None]:
    """``(user, repo)`` from "octocat", "@octocat", "github.com/octocat" or a repository
    link (``repo`` is None for a user). Raises GitHubError for anything else."""
    text = text.strip()
    if match := _USER.match(text):
        return match.group(1), None
    if match := _URL.match(text):
        return match.group(1), match.group(2) or None
    raise GitHubError("Enter a GitHub username or a github.com link.")


def username(contact_github: str) -> str:
    """The username in a resume's GitHub field, or "" when it holds none."""
    try:
        user, _repo = parse_target(contact_github)
    except GitHubError:
        return ""
    return user


def _headers() -> dict[str, str]:
    headers = {"X-GitHub-Api-Version": "2022-11-28"}
    if token := config.credential("GITHUB_TOKEN").strip():
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _api(fetcher: Fetcher, path: str) -> object:
    try:
        return fetcher.get_json(f"{API}{path}", headers=_headers())
    except FetchError as exc:
        if exc.status in (403, 429):
            raise GitHubError(
                "GitHub's limit on reads was reached. Add a GitHub token in Settings, "
                "or try again in an hour."
            ) from None
        if exc.status == 404:
            raise GitHubError("GitHub has no public account or repository by that name.") from None
        raise GitHubError(f"GitHub could not be read: {exc}") from None


def guard_flags(found: posting_guard.GuardFindings) -> list[str]:
    """What the guard found in an evidence text, in plain words."""
    out: list[str] = []
    if found.instruction_like:
        quote = found.instruction_like[0]
        out.append(f"Has text addressed to AI tools, read as data only: “{quote}”")
    if found.invisible_flagged or found.invisible_chars.get("tag"):
        out.append("Had hidden characters, which were removed.")
    return out


def _clean_markdown(text: str) -> str:
    text = _FENCE.sub(" ", text)
    text = _IMAGE.sub(" ", text)
    text = _LINK.sub(r"\1", text)
    return _TAG.sub(" ", text)


def _readme(fetcher: Fetcher, repo: Repo) -> tuple[str, list[str]]:
    base = raw_readme_url(repo.url).rsplit("/", 1)[0]
    for name in _READMES:
        try:
            fetched = fetcher.get(f"{base}/{name}")
        except FetchError:
            continue
        text, findings = pages.clean(_clean_markdown(fetched.text))
        return text, guard_flags(findings)
    return "", []


def attribution(fork: bool, contributors: object, user: str) -> tuple[Attribution, float | None]:
    """Whose work a repository is, from GitHub's contributor list."""
    if fork:
        return "fork", None
    listed = contributors if isinstance(contributors, list) else []
    rows = [r for r in listed if isinstance(r, dict)]
    total = sum(int(r.get("contributions") or 0) for r in rows)
    mine = sum(
        int(r.get("contributions") or 0)
        for r in rows
        if str(r.get("login") or "").casefold() == user.casefold()
    )
    if not total or not mine:
        return "unknown", None
    share = round(mine / total, 2)
    return ("own" if share >= OWN_SHARE else "contributed"), share


def _repo(fetcher: Fetcher, row: dict, user: str) -> Repo:
    owner = str((row.get("owner") or {}).get("login") or "")
    repo = Repo(
        owner=owner,
        name=str(row.get("name") or ""),
        url=str(row.get("html_url") or f"https://github.com/{owner}/{row.get('name')}"),
        description=" ".join(str(row.get("description") or "").split()),
        fork=bool(row.get("fork")),
        pushed_at=str(row.get("pushed_at") or "")[:10],
    )
    if repo.fork:
        repo.attribution = "fork"
        return repo
    path = f"/repos/{quote(owner)}/{quote(repo.name)}"
    languages = _api(fetcher, f"{path}/languages")
    if isinstance(languages, dict):
        repo.languages = [str(k) for k in languages][:8]
    try:
        contributors = _api(fetcher, f"{path}/contributors?per_page=100")
    except GitHubError as exc:
        if "limit" in str(exc):
            raise
        contributors = []  # an empty repository answers 204, which reads as an error
    repo.attribution, repo.commit_share = attribution(False, contributors, user)
    repo.readme, repo.flags = _readme(fetcher, repo)
    return repo


def read(target: str, fetcher: Fetcher, *, user: str = "") -> tuple[list[Repo], list[str]]:
    """``(repositories, warnings)`` for a username or a repository link. ``user`` is
    whose commits count as the student's, defaulting to the target's owner."""
    owner, name = parse_target(target)
    user = user or owner
    if name:
        row = _api(fetcher, f"/repos/{quote(owner)}/{quote(name)}")
        if not isinstance(row, dict):
            raise GitHubError("GitHub sent an answer that could not be read.")
        return [_repo(fetcher, row, user)], []
    rows = _api(fetcher, f"/users/{quote(owner)}/repos?type=owner&sort=pushed&per_page={MAX_REPOS}")
    if not isinstance(rows, list):
        raise GitHubError("GitHub sent an answer that could not be read.")
    repos: list[Repo] = []
    warnings: list[str] = []
    for row in rows[:MAX_REPOS]:
        if not isinstance(row, dict):
            continue
        try:
            repos.append(_repo(fetcher, row, user))
        except GitHubError as exc:
            warnings.append(f"Stopped after {len(repos)} repositories: {exc}")
            break
    return repos, warnings


def repo_text(repo: Repo) -> str:
    """The source text a scan reads."""
    lines = [f"Repository: {repo.full_name}"]
    if repo.description:
        lines.append(f"Description: {repo.description}")
    if repo.languages:
        lines.append(f"Languages (detected by GitHub): {', '.join(repo.languages)}")
    if repo.readme:
        lines += ["README:", repo.readme]
    return "\n".join(lines)
