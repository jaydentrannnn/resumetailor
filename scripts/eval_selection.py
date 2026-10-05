"""Compare default and coverage-aware bullet selection on a profile's saved runs.

No model calls: each saved run's `requirements.json` and its cached relevance scores
(keyword-only when the cache has moved on) are replayed through entry choice and bullet
selection at the run's final bullet count, once per mode. Reports how many posting
keywords the selected bullets show and how much semantic relevance they keep.

Approximations, so read the result as a comparison, not a reproduction: the current
master resume stands in for the one each run used, run-time exclusions are not
re-applied, and the fit loop's later drops and top-ups are not replayed.

    python scripts\\eval_selection.py [--workspace <id>] [--limit N] [--per-run]

For the desktop app's profiles, point RESUME_TAILOR_DATA_DIR, _OUTPUT_DIR,
_TEMPLATES_DIR and _CACHE_DIR at the matching folders under
%LOCALAPPDATA%\\ResumeTailorData first; the template decides which sections exist.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from statistics import mean

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from resume_tailor import config, workspace  # noqa: E402
from resume_tailor.content import data  # noqa: E402
from resume_tailor.pipeline import fit_selection, relevance, selection  # noqa: E402
from resume_tailor.pipeline.jd import JobRequirements  # noqa: E402
from resume_tailor.pipeline.relevance import ScoreTable  # noqa: E402


def _semantic(resume, requirements: JobRequirements) -> dict[str, float] | None:
    path = relevance._score_cache_path(resume.all_bullets(), requirements)
    if not path.exists():
        return None
    table = ScoreTable.model_validate_json(path.read_text(encoding="utf-8"))
    return {s.id: s.relevance for s in table.scores}


def _select(resume, requirements, semantic, limit: int, coverage: bool) -> list:
    config.COVERAGE_SELECTION = coverage
    cap = config.MAX_BULLETS_PER_ENTRY
    entries = fit_selection.choose_entries(
        resume, requirements, semantic=semantic, max_per_entry=cap,
    )
    pools, weights = fit_selection._section_pools(
        resume, entries, config.EXPERIENCE_BULLET_SHARE,
    )
    return selection.select_within_entries(
        entries, requirements, limit=limit, semantic=semantic, max_per_entry=cap,
        pools=pools, weights=weights,
    )


def _measure(bullets, requirements: JobRequirements, semantic) -> dict[str, float]:
    shown = {
        kw.canonical for kw in requirements.keywords
        for b in bullets if selection._matches(kw, set(b.tags))
    }
    must = {kw.canonical for kw in requirements.keywords
            if kw.importance == "must_have" and kw.kind != "soft"}
    return {
        "must_have": len(must & shown),
        "must_total": len(must),
        "keywords": len(shown),
        "semantic": sum((semantic or {}).get(b.id, 0.0) for b in bullets),
    }


def _runs(jobs_dir: Path, limit: int | None):
    dirs = sorted(
        (p for p in jobs_dir.iterdir() if (p / "requirements.json").exists()),
        key=lambda p: p.stat().st_mtime, reverse=True,
    )
    for job_dir in dirs[:limit] if limit else dirs:
        try:
            run = json.loads((job_dir / "run.json").read_text(encoding="utf-8"))
            requirements = JobRequirements.model_validate_json(
                (job_dir / "requirements.json").read_text(encoding="utf-8")
            )
        except (OSError, ValueError):
            continue
        selected = (run.get("report") or {}).get("bullets_selected")
        if selected:
            yield job_dir.name, requirements, int(selected)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--workspace")
    parser.add_argument("--limit", type=int, help="newest N runs only")
    parser.add_argument("--per-run", action="store_true", help="print every changed run")
    args = parser.parse_args(argv)
    workspace.bootstrap(workspace_id=args.workspace, migrate=False)
    resume = data.load()

    rows = []
    for job_id, requirements, limit in _runs(config.OUTPUT_DIR / "jobs", args.limit):
        semantic = _semantic(resume, requirements)
        base = _select(resume, requirements, semantic, limit, coverage=False)
        cover = _select(resume, requirements, semantic, limit, coverage=True)
        before, after = (_measure(b, requirements, semantic) for b in (base, cover))
        changed = len({b.id for b in base} ^ {b.id for b in cover}) // 2
        rows.append((job_id, semantic is not None, before, after, changed))
        if args.per_run and changed:
            print(
                f"{job_id}: must-haves {before['must_have']}->{after['must_have']}"
                f"/{before['must_total']}, keywords {before['keywords']}->{after['keywords']}, "
                f"semantic {before['semantic']:.1f}->{after['semantic']:.1f}, "
                f"{changed} bullet(s) swapped"
            )
    if not rows:
        print("No saved runs with requirements and a report.")
        return 1

    def avg(key: str, which: int) -> float:
        return mean(r[which][key] for r in rows)

    scored = [r for r in rows if r[1]]
    print(f"\nRuns: {len(rows)} ({len(scored)} with cached semantic scores)")
    print(f"Runs where selection changed: {sum(1 for r in rows if r[4])}")
    print(f"Must-haves shown, mean: {avg('must_have', 2):.2f} -> {avg('must_have', 3):.2f}"
          f" of {mean(r[2]['must_total'] for r in rows):.2f}")
    print(f"Runs gaining / losing a must-have: "
          f"{sum(1 for r in rows if r[3]['must_have'] > r[2]['must_have'])} / "
          f"{sum(1 for r in rows if r[3]['must_have'] < r[2]['must_have'])}")
    print(f"Keywords shown, mean: {avg('keywords', 2):.2f} -> {avg('keywords', 3):.2f}")
    if scored:
        print(f"Semantic kept (scored runs), mean: "
              f"{mean(r[2]['semantic'] for r in scored):.1f} -> "
              f"{mean(r[3]['semantic'] for r in scored):.1f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
