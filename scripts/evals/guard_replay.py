"""Replay saved first drafts through two guard versions: which retries would change?

No model calls. A retry probe (or any eval that recorded `result.rejected`) stores each
factual-retry batch as `{bullet_id: {"source", "draft", "offenders"}}`; probe workers
overlapped, so the same batch can appear under several cases and is deduplicated here by
content. Each bullet is rebuilt from the probe sandbox's own master resume (tags
included) and must match the recorded source text exactly, or the replay aborts.

The baseline guard runs as a whole package from another source tree (a `git worktree` of
the commit before a guard change) in a subprocess, so it never calls newly modified
helpers. Two outputs: individual violations removed or retained (by kind), and whole
retry batches eliminated because no violation remains.

    git worktree add <tmp>/base <commit-before>
    python scripts/evals/guard_replay.py --baseline-src <tmp>/base/src

Self-contained on purpose: `--src` must be on `sys.path` before `resume_tailor` loads.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
_KINDS = ("missing_number", "rebound", "authorship")


def kind(offender: str) -> str:
    """`missing_number` / `rebound` / `authorship` by prefix; anything else is a term."""
    head = offender.split(":", 1)[0]
    return head if ":" in offender and head in _KINDS else "term"


def load_batches(cases_path: Path) -> list[dict[str, dict]]:
    """The distinct retry batches recorded under `result.rejected`, in first-seen order."""
    seen: dict[str, dict[str, dict]] = {}
    for line in cases_path.read_text(encoding="utf-8").splitlines():
        record = json.loads(line)
        if record.get("status") != "ok":
            continue
        for batch in record.get("result", {}).get("rejected", []):
            seen.setdefault(json.dumps(batch, sort_keys=True), batch)
    return list(seen.values())


def evaluate(batches: list[dict[str, dict]], eval_dir: Path, workspace_id: str) -> dict:
    """Run this interpreter's `guard_offenders` over every rejected draft."""
    sandbox = eval_dir / "sandbox"
    os.environ.update({
        "RESUME_TAILOR_DATA_DIR": str(sandbox / "data"),
        "RESUME_TAILOR_OUTPUT_DIR": str(sandbox / "output"),
        "RESUME_TAILOR_CACHE_DIR": str(sandbox / "cache"),
        "RESUME_TAILOR_TEMPLATES_DIR": str(sandbox / "templates"),
        "RESUME_TAILOR_LOG_DIR": "off",
    })
    import resume_tailor
    from resume_tailor import workspace
    from resume_tailor.content import data
    from resume_tailor.pipeline import bullet_checks

    workspace.bootstrap(workspace_id=workspace_id, migrate=False)
    by_id = {b.id: b for b in data.load().all_bullets()}
    results = []
    for batch in batches:
        row = {}
        for bid, rec in batch.items():
            source = by_id.get(bid)
            if source is None or source.text != rec["source"]:
                raise SystemExit(f"snapshot mismatch for {bid!r}: the sandbox resume changed")
            row[bid] = bullet_checks.guard_offenders([source], rec["draft"], preserve_numbers=True)
        results.append(row)
    return {"package": str(Path(resume_tailor.__file__).parent), "results": results}


def compare(batches: list[dict[str, dict]], old: list[dict], new: list[dict]) -> dict:
    """Violations removed/retained/added by kind, and batches the new guard eliminates."""
    removed, retained, added = Counter(), Counter(), Counter()
    examples: list[dict] = []
    eliminated = 0
    for batch, before, after in zip(batches, old, new, strict=True):
        if not any(after.values()):
            eliminated += 1
        for bid in batch:
            b, a = before.get(bid, []), after.get(bid, [])
            for o in b:
                (retained if o in a else removed)[kind(o)] += 1
            for o in a:
                if o not in b:
                    added[kind(o)] += 1
            if b != a:
                examples.append({"id": bid, "draft": batch[bid]["draft"], "old": b, "new": a})
    return {
        "batches": len(batches),
        "batches_with_violations_old": sum(1 for row in old if any(row.values())),
        "batches_eliminated": eliminated,
        "violations": {"removed": dict(removed), "retained": dict(retained), "added": dict(added)},
        "changed": examples,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--eval-dir", type=Path, default=ROOT / "output" / "eval" / "retry-probe")
    parser.add_argument("--workspace", default="default")
    parser.add_argument("--src", type=Path, default=ROOT / "src", help="resume_tailor source tree")
    parser.add_argument("--baseline-src", type=Path, help="older source tree to compare against")
    parser.add_argument("--emit", type=Path, help="write this tree's results as JSON and stop")
    args = parser.parse_args(argv)

    sys.path.insert(0, str(args.src))
    batches = load_batches(args.eval_dir / "cases.jsonl")
    current = evaluate(batches, args.eval_dir, args.workspace)
    if args.emit:
        args.emit.write_text(json.dumps(current), encoding="utf-8")
        return 0
    if args.baseline_src is None:
        parser.error("--baseline-src is required unless --emit is given")
    out = args.eval_dir / "guard_replay.baseline.json"
    subprocess.run(
        [sys.executable, __file__, "--eval-dir", str(args.eval_dir), "--workspace",
         args.workspace, "--src", str(args.baseline_src), "--emit", str(out)],
        check=True,
    )
    baseline = json.loads(out.read_text(encoding="utf-8"))
    if Path(baseline["package"]).resolve() == Path(current["package"]).resolve():
        raise SystemExit("baseline and current loaded the same package; check --baseline-src")
    summary = compare(batches, baseline["results"], current["results"])
    summary["packages"] = {"baseline": baseline["package"], "current": current["package"]}
    (args.eval_dir / "guard_replay.json").write_text(
        json.dumps(summary, indent=1, ensure_ascii=False), encoding="utf-8"
    )
    print(json.dumps({k: v for k, v in summary.items() if k != "changed"}, indent=1))
    for change in summary["changed"]:
        print(f"- {change['id']}: {change['old']} -> {change['new']}\n    {change['draft'][:200]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
