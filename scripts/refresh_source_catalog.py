"""Maintainer tool: check the source catalog and propose next year's README URLs.

    python scripts/refresh_source_catalog.py --check
    python scripts/refresh_source_catalog.py [--write proposed.json]

``--check`` fetches every README entry in ``src/resume_tailor/apply/discovery/catalog/sources.json``
and prints how many rows its parser reads with the entry's categories (a 0 is a broken
entry). Without it, the script lists each README owner's repositories through the GitHub
API and looks for a newer year of every entry's repo: the repo name with its year
replaced by a later one (``Summer2027-`` -> ``Summer2028-``, ``2027-SWE-``,
``2027-AI-``, ``2027QuantInternships``, a ``-2027`` suffix, ``New-Grad-2027``). A
candidate is proposed only when its README parses to more than 0 rows with the same
kind and categories. The proposals print as a diff; ``--write`` saves a proposed
catalog with each changed entry's ``version`` bumped to today, for review.

It never edits the bundled catalog in place and never commits. Set ``GITHUB_TOKEN`` to
raise the GitHub API rate limit. Network use only — no LLM.
"""

from __future__ import annotations

import argparse
import copy
import json
import os
import re
import sys
from datetime import date
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from resume_tailor.apply.discovery import sources  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "src" / "resume_tailor" / "apply" / "discovery" / "catalog" / "sources.json"
_RAW_RE = re.compile(r"^https://raw\.githubusercontent\.com/([^/]+)/([^/]+)/([^/]+)/(.+)$")
_YEAR_RE = re.compile(r"20\d\d")


def _headers() -> dict[str, str]:
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "resumetailor-catalog-refresh",
    }
    token = os.environ.get("GITHUB_TOKEN", "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _fetch(url: str) -> str:
    response = httpx.get(url, follow_redirects=True, timeout=30.0)
    response.raise_for_status()
    return response.text


def row_count(template: dict, text: str | None = None) -> int:
    """Rows the parser reads for a README template (fetches the README unless given)."""
    body = text if text is not None else _fetch(template["url"])
    return len(sources.parse_source_text(template["kind"], body, template.get("categories") or []))


def owner_repos(owner: str) -> dict[str, str]:
    """``{repo name: default branch}`` for a GitHub user or organisation."""
    repos: dict[str, str] = {}
    page = 1
    while True:
        response = httpx.get(
            f"https://api.github.com/users/{owner}/repos",
            params={"per_page": 100, "page": page},
            headers=_headers(),
            timeout=30.0,
        )
        response.raise_for_status()
        batch = response.json()
        repos.update({repo["name"]: repo.get("default_branch") or "main" for repo in batch})
        if len(batch) < 100:
            return repos
        page += 1


def newer_names(repo: str, available: dict[str, str]) -> list[str]:
    """Repos in ``available`` named like ``repo`` with a later year, newest first."""
    years = [int(y) for y in _YEAR_RE.findall(repo)]
    if not years:
        return []
    current = max(years)
    found = []
    for later in range(current + 3, current, -1):
        candidate = repo.replace(str(current), str(later))
        if candidate in available:
            found.append(candidate)
    return found


def check(catalog: dict) -> int:
    """Print each README entry's row count; return how many read 0 rows or failed."""
    broken = 0
    for entry in catalog["entries"]:
        template = entry["template"]
        if template["kind"] in {"job_search", "ats_board"}:
            print(f"  {entry['id']:40} {template['kind']} (not a README; skipped)")
            continue
        try:
            count = row_count(template)
        except Exception as exc:  # noqa: BLE001 - report and keep going
            count, note = 0, f" error: {exc}"
        else:
            note = ""
        broken += count == 0
        print(f"  {entry['id']:40} rows={count:6}{note}")
    return broken


def propose(catalog: dict) -> dict:
    """A copy of ``catalog`` with newer-year README URLs where one parses to rows."""
    proposed = copy.deepcopy(catalog)
    listings: dict[str, dict[str, str]] = {}
    today = date.today().strftime("%Y.%m.%d")
    for entry in proposed["entries"]:
        template = entry["template"]
        match = _RAW_RE.match(template.get("url") or "")
        if not match:
            continue
        owner, repo, _branch, path = match.groups()
        if owner not in listings:
            try:
                listings[owner] = owner_repos(owner)
            except Exception as exc:  # noqa: BLE001
                print(f"  {owner}: could not list repos ({exc})")
                listings[owner] = {}
        for candidate in newer_names(repo, listings[owner]):
            url = f"https://raw.githubusercontent.com/{owner}/{candidate}/{listings[owner][candidate]}/{path}"
            try:
                text = _fetch(url)
            except Exception as exc:  # noqa: BLE001
                print(f"  {entry['id']}: {url} unreadable ({exc})")
                continue
            count = row_count(template, text)
            if count == 0:
                detected = sources.detect_format(text)
                sections = sources.source_sections(detected, text) if detected else []
                print(
                    f"  {entry['id']}: {url} reads 0 rows with the current categories"
                    f" (detected {detected}; sections {sections})"
                )
                continue
            print(f"- {entry['id']}: {template['url']}\n+ {entry['id']}: {url}  (rows={count})")
            template["url"] = url
            entry["version"] = today
            break
    return proposed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--check", action="store_true", help="count rows for every current entry")
    parser.add_argument(
        "--write", type=Path, help="save the proposed catalog here (never in place)"
    )
    args = parser.parse_args(argv)
    catalog = json.loads(CATALOG.read_text(encoding="utf-8"))
    if args.check:
        broken = check(catalog)
        print(f"{broken} broken entr{'y' if broken == 1 else 'ies'}")
        return 1 if broken else 0
    proposed = propose(catalog)
    if proposed == catalog:
        print("No newer README URLs found.")
        return 0
    if args.write:
        if args.write.resolve() == CATALOG.resolve():
            parser.error("--write must not overwrite the bundled catalog; review it first")
        text = json.dumps(proposed, indent=2, ensure_ascii=False) + "\n"
        args.write.write_text(text, encoding="utf-8")
        print(f"Proposed catalog written to {args.write}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
