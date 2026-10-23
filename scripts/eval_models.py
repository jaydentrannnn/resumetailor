"""Replay saved postings through one pipeline stage per arm and compare the arms.

Each arm calls the real stage function (`rewrite_bullets`, `expand_experience`,
`jd.extract`, or experiment E's hybrid extractor) with the arm's model and effort
pinned, against a sandbox copy of the desktop app's data, never the live folders.
Results append to `output/eval/<name>/cases.jsonl`; rerunning the same command skips
finished tasks, so an interrupted run resumes for free. `summary.md` holds the paired
comparison, cost, and the PASS/FAIL decision rules (`evals/report.py`,
`evals/report_extract.py`).

Effort experiments (arms are efforts; the first is the baseline):

    python scripts\\eval_models.py rewrite --arms medium,low --limit 80 --control 30
    python scripts\\eval_models.py expand --arms medium,low --limit 40 --control 20

Experiment E (arms are `current` and `hybrid`; fetched non-tech postings included):

    python scripts\\eval_models.py fetch
    python scripts\\eval_models.py extract --limit 80 --control 30
    python scripts\\eval_models.py extract --limit 30 --spec <json spec> --tag azure

Variant experiments (arms `current` vs `gaps` / `scope`; same model and effort; each run's
own tailored bullets; the cover sample keeps runs with an unmet must-have):

    python scripts\\eval_models.py cover --limit 30 --control 15
    python scripts\\eval_models.py review --limit 30 --control 15

Judge (a different model family; Azure OpenAI via its OpenAI-compatible v1 endpoint):

    python scripts\\eval_models.py judge-key --judge-url <url> --judge-model <deployment>
    python scripts\\eval_models.py judge --name rewrite --judge-url <url> --judge-model <deployment>
    python scripts\\eval_models.py report --name rewrite

`judge-key` asks for the key and saves it in the app's secret store; `AZURE_OPENAI_API_KEY`
in the environment is used instead when set. Arms run on the profile's Light model
(Settings -> AI model) unless `--spec` names another (`provider:model[@base_url]` or a
JSON spec). Start with `--limit 10`.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from evals import corpus, report, sandbox  # noqa: E402  (no resume_tailor imports yet)

EVAL_ROOT = ROOT / "output" / "eval"
NONTECH_DIR = EVAL_ROOT / "corpus" / "nontech"
#: Which effort step (`config.EFFORT_STEPS`) each effort experiment varies.
_STEP = {"rewrite": "rewrite", "expand": "expand"}
#: Sites whose fill pastes the expansion (`preparation.EXPANSION_ATS`).
_EXPANSION_ATS = {"workday", "smartrecruiters"}
_METRICS = {
    "rewrite": ["fallback_rate", "guard_offenders", "mirror_rate", "must_mirrored",
                "over_length", "under_length", "verb_collisions", "phrase_collisions",
                "changed_rate", "mean_chars"],
    "expand": ["entries", "empty_entries", "bullets", "guard_dropped", "chars", "over_limit"],
    "cover": ["factual_left", "gap_claimed", "gap_mentioned", "style_left", "ai_tells", "words"],
    "review": ["guard_dropped_rate", "findings", "cuts", "rewrites", "stretch", "consistency"],
}
_METRICS["cover-company"] = _METRICS["cover"]
_METRICS["review-note"] = _METRICS["review"]
#: Variant experiments: `(baseline arm, candidate arm, Replay method per arm)`.
_VARIANTS = {
    "cover": ("current", "gaps", {"current": "cover", "gaps": "cover_gaps"}),
    "cover-company": ("current", "company", {"current": "cover", "company": "cover_company"}),
    "review": ("current", "scope", {"current": "review", "scope": "review_scope"}),
    "review-note": ("current", "note", {"current": "review", "note": "review_note"}),
}
#: The profile each fetched group runs against (a finance resume for finance postings).
_GROUP_WORKSPACE = {"finance": "nina", "nontech": "default"}


def _parse_spec(raw: str | None):
    if raw is None:
        return None
    return json.loads(raw) if raw.lstrip().startswith("{") else raw


def _args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("stage", choices=[
        "rewrite", "expand", "extract", "cover", "cover-company", "review", "review-note",
        "fetch", "judge", "judge-key", "report"])
    parser.add_argument("--arms", help="effort arms, baseline first (default medium,low)")
    parser.add_argument("--limit", default="10", help="saved postings to sample, or 'all'")
    parser.add_argument("--control", type=int, default=0,
                        help="rerun the baseline (extract: both methods) on N cases")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--workspace", default="default")
    parser.add_argument("--spec", help="model for every arm (default: the Light model)")
    parser.add_argument("--tag", help="extract: suffix for a second model's arms, e.g. azure")
    parser.add_argument("--name", help="eval folder under output/eval (default: the stage)")
    parser.add_argument("--judge-url", help="judge's OpenAI-compatible base URL "
                        "(Azure: https://<resource>.openai.azure.com/openai/v1/)")
    parser.add_argument("--judge-model", help="judge model / Azure deployment name")
    return parser.parse_args(argv)


# -- shared ------------------------------------------------------------------------------


def _read_meta(eval_dir: Path) -> dict:
    path = eval_dir / "meta.json"
    return json.loads(path.read_text("utf-8")) if path.exists() else {}


def _write_meta(eval_dir: Path, meta: dict) -> None:
    (eval_dir / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")


def _summary(eval_dir: Path) -> str:
    from evals import arms as arms_mod
    from evals import judge

    meta = _read_meta(eval_dir)
    records = arms_mod.Results(eval_dir / "cases.jsonl").records()
    verdicts = judge.Verdicts(judge.verdicts_file(eval_dir)).records()
    if meta["stage"] == "extract":
        from evals import report_extract

        text = report_extract.markdown(records, verdicts, (meta.get("tags") or [None])[0])
    else:
        stage, base, cand = meta["stage"], meta["base"], meta["cand"]
        grouped = report.by_arm(records)
        checks = {"rewrite": report.REWRITE_CHECKS, "expand": report.EXPAND_CHECKS,
                  "cover": report.COVER_CHECKS, "cover-company": report.COVER_CHECKS,
                  "review": report.REVIEW_CHECKS, "review-note": report.REVIEW_CHECKS}[stage]
        rules = report.gate(grouped, verdicts, base, cand, checks=checks)
        errors = sum(1 for r in records if r.get("status") == "error")
        text = report.markdown(f"{stage}: {base} vs {cand}", grouped, _METRICS[stage],
                               base, cand, rules=rules, model=meta["model"], errors=errors)
    (eval_dir / "summary.md").write_text(text, encoding="utf-8")
    return text


def _sandbox(eval_dir: Path) -> None:
    """Point config at the sandbox. Must run before anything imports resume_tailor."""
    os.environ.update(sandbox.environment(sandbox.prepare(eval_dir)))


def _progress(record: dict) -> None:
    note = record.get("error", "")[:120] if record["status"] == "error" else (
        f"{record['usage']['wall_ms'] / 1000:.1f}s")
    print(f"  {record['status']:5} {record['key']}  {note}", flush=True)


def _model(spec) -> str:
    return spec["model"] if isinstance(spec, dict) else str(spec)


# -- effort experiments ------------------------------------------------------------------


def _run_effort(args: argparse.Namespace, eval_dir: Path) -> int:
    _sandbox(eval_dir)
    from evals import arms as arms_mod
    from evals.stages import Replay

    efforts = [e.strip() for e in (args.arms or "medium,low").split(",") if e.strip()]
    base, cand = efforts[0], efforts[-1]
    replay = Replay(args.workspace)
    cases = [c for c in corpus.load_saved(sandbox.live_jobs_dir(args.workspace), args.workspace)
             if replay.can_rewrite(c)]
    if args.stage == "expand":
        cases = [c for c in cases if c.ats in _EXPANSION_ATS]
    chosen = corpus.sample(cases, None if args.limit == "all" else int(args.limit),
                           seed=args.seed)
    spec = _parse_spec(args.spec) or replay.light_spec
    step = _STEP[args.stage]
    tasks = [(c, arms_mod.Arm(e, spec, {step: e})) for e in efforts for c in chosen]
    control = arms_mod.Arm(base, spec, {step: base}, repeat=1)
    tasks += [(c, control) for c in chosen[: args.control]]
    _write_meta(eval_dir, {
        "stage": args.stage, "base": base, "cand": cand, "model": _model(spec),
        "workspace": args.workspace, "spec": spec, "seed": args.seed,
        "cases": [c.case_id for c in chosen]})
    print(f"{len(chosen)} case(s) of {len(cases)} eligible; {len(tasks)} task(s) "
          f"on {_model(spec)}; writing {eval_dir}")
    arms_mod.run(tasks, getattr(replay, args.stage), arms_mod.Results(eval_dir / "cases.jsonl"),
                 setup=replay.setup, workers=args.workers, out_dir=eval_dir,
                 progress=_progress)
    print(_summary(eval_dir))
    return 0


# -- variant experiments (cover letter gap bridges, broader review) ------------------------


def _run_variant(args: argparse.Namespace, eval_dir: Path) -> int:
    """Baseline vs candidate on each run's own tailored bullets, same model and effort;
    the cover experiment samples only runs with at least one unmet must-have."""
    _sandbox(eval_dir)
    from evals import arms as arms_mod
    from evals.stages import Replay

    base, cand, methods = _VARIANTS[args.stage]
    replay = Replay(args.workspace)
    cases = [c for c in corpus.load_saved(sandbox.live_jobs_dir(args.workspace), args.workspace)
             if replay.can_cover(c)]
    if args.stage == "cover":
        cases = [c for c in cases if replay.unmet(c)]
    if args.stage == "cover-company":
        cases = [c for c in cases if replay.company_name(c)]
    chosen = corpus.sample(cases, None if args.limit == "all" else int(args.limit),
                           seed=args.seed)
    spec = _parse_spec(args.spec) or replay.light_spec
    if args.stage == "cover-company":
        print(f"researching {len(chosen)} compan(ies) once, then freezing the facts")
        arms_mod.run([(c, arms_mod.Arm("research", spec)) for c in chosen],
                     replay.research_company, arms_mod.Results(eval_dir / "research.jsonl"),
                     setup=replay.setup, workers=args.workers, out_dir=eval_dir,
                     progress=_progress)
        replay.frozen_facts = _frozen_facts(eval_dir)
    _write_meta(eval_dir, {
        "stage": args.stage, "base": base, "cand": cand, "model": _model(spec),
        "workspace": args.workspace, "spec": spec, "seed": args.seed,
        "cases": [c.case_id for c in chosen]})
    print(f"{len(chosen)} case(s) of {len(cases)} eligible on {_model(spec)}; writing {eval_dir}")
    results = arms_mod.Results(eval_dir / "cases.jsonl")
    for name in (base, cand):
        tasks = [(c, arms_mod.Arm(name, spec)) for c in chosen]
        if name == base:
            tasks += [(c, arms_mod.Arm(base, spec, repeat=1)) for c in chosen[: args.control]]
        arms_mod.run(tasks, getattr(replay, methods[name]), results, setup=replay.setup,
                     workers=args.workers, out_dir=eval_dir, progress=_progress)
    print(_summary(eval_dir))
    return 0


def _frozen_facts(eval_dir: Path) -> dict[str, list[str]]:
    """Company facts per case from the research pass (L4.6), `{}` for other stages."""
    from evals import arms as arms_mod

    records = arms_mod.Results(eval_dir / "research.jsonl").records()
    return {r["case"]: r["result"]["facts"] for r in records if r.get("status") == "ok"}


# -- experiment E ------------------------------------------------------------------------


def _all_cases(limit: str, seed: int) -> tuple[list, list]:
    """(chosen cases: sampled saved tech postings + every fetched one, every saved one)."""
    saved = corpus.load_saved(sandbox.live_jobs_dir("default"), "default")
    fetched = corpus.load_texts(NONTECH_DIR)
    tech = corpus.sample(saved, None if limit == "all" else int(limit), seed=seed)
    return tech + fetched, saved


def _run_extract(args: argparse.Namespace, eval_dir: Path) -> int:
    _sandbox(eval_dir)
    from evals import arms as arms_mod
    from evals.stages import Replay

    chosen, saved = _all_cases(args.limit, args.seed)
    controls = {c.case_id for c in corpus.sample(
        chosen, args.control, seed=args.seed, stratum=lambda c: c.group)} if args.control else set()
    meta = _read_meta(eval_dir) or {"stage": "extract", "base": "current", "cand": "hybrid",
                                    "seed": args.seed, "tags": []}
    if args.tag and args.tag not in meta["tags"]:
        meta["tags"].append(args.tag)
    results = arms_mod.Results(eval_dir / "cases.jsonl")
    for workspace_id in sorted({c.workspace for c in chosen}):
        replay = Replay(workspace_id)
        replay.build_dictionary(saved)
        spec = _parse_spec(args.spec) or replay.light_spec
        meta.setdefault("model", _model(spec))
        cases = [c for c in chosen if c.workspace == workspace_id]
        suffix = f"@{args.tag}" if args.tag else ""
        print(f"[{workspace_id}] {len(cases)} case(s) on {_model(spec)}", flush=True)
        for method in ("current", "hybrid"):
            arm = arms_mod.Arm(method + suffix, spec)
            tasks = [(c, arm) for c in cases]
            if not suffix:
                rerun = arms_mod.Arm(method, spec, repeat=1)
                tasks += [(c, rerun) for c in cases if c.case_id in controls]
            stage = replay.extract if method == "current" else replay.hybrid
            arms_mod.run(tasks, stage, results, setup=replay.setup, workers=args.workers,
                         out_dir=eval_dir, progress=_progress)
    _write_meta(eval_dir, meta)
    print(_summary(eval_dir))
    return 0


def _run_fetch(args: argparse.Namespace) -> int:
    from evals import fetch

    from resume_tailor.apply.discovery import boards

    lists = boards.watchlists()
    finance = [b for name in ("banking", "consulting", "finance") for b in lists.get(name, [])]
    for group, source, total in (("finance", finance, 25), ("nontech", fetch.OTHER_BOARDS, 15)):
        have = fetch.fetch(NONTECH_DIR, source, group=group,
                           workspace=_GROUP_WORKSPACE[group], total=total)
        print(f"{group}: {have} posting(s) in {NONTECH_DIR}")
    return 0


# -- judge -------------------------------------------------------------------------------


def _judge_spec(args: argparse.Namespace) -> dict:
    from evals import judge

    if not (args.judge_url and args.judge_model):
        raise SystemExit("needs --judge-url and --judge-model")
    spec = judge.spec(args.judge_url, args.judge_model)
    if key := os.environ.get(judge.KEY_ENV):
        # `config.credential` reads the environment first, under the spec's own name.
        os.environ[spec["credential_ref"]] = key
    return spec


def _run_judge(args: argparse.Namespace, eval_dir: Path) -> int:
    meta = _read_meta(eval_dir)
    _sandbox(eval_dir)
    from evals import arms as arms_mod
    from evals import judge
    from evals.stages import Replay

    spec = _judge_spec(args)
    stage, base, cand = meta["stage"], meta["base"], meta["cand"]
    grouped = report.by_arm(arms_mod.Results(eval_dir / "cases.jsonl").records())
    cases = corpus.load_saved(sandbox.live_jobs_dir(meta.get("workspace", "default")),
                              meta.get("workspace", "default")) + corpus.load_texts(NONTECH_DIR)
    by_id = {c.case_id: c for c in cases}
    replays: dict[str, Replay] = {}
    jobs = []
    for a, b in ((f"{base}#0", f"{cand}#0"), (f"{base}#0", f"{base}#1")):
        for case_id in sorted(set(grouped.get(a, {})) & set(grouped.get(b, {}))):
            case = by_id[case_id]
            if case.workspace not in replays:
                replays[case.workspace] = Replay(case.workspace)
                replays[case.workspace].frozen_facts = _frozen_facts(eval_dir)
            build, out_a, out_b = replays[case.workspace].judge_inputs(
                stage, case, grouped[a][case_id]["result"], grouped[b][case_id]["result"])
            jobs.append((case_id, a, b, build, out_a, out_b))
    print(f"{len(jobs)} pair(s) to judge on {spec['model']}")

    def progress(record: dict) -> None:
        print(f"  {record.get('winner', 'error'):5} {record['key']}  "
              f"{record.get('error', '')[:120]}", flush=True)

    judge.run(jobs, stage, spec, judge.Verdicts(judge.verdicts_file(eval_dir)),
              workers=args.workers, progress=progress)
    print(_summary(eval_dir))
    return 0


def main(argv: list[str] | None = None) -> int:
    args = _args(argv)
    if args.stage == "judge-key":
        import getpass

        from evals import judge

        judge.save_key(_judge_spec(args), getpass.getpass("Judge API key: ").strip())
        print("Saved in the app's secret store.")
        return 0
    if args.stage == "fetch":
        return _run_fetch(args)
    if args.stage in {"report", "judge"} and not args.name:
        raise SystemExit(f"{args.stage} needs --name <eval folder>")
    eval_dir = EVAL_ROOT / (args.name or args.stage)
    if args.stage == "report":
        print(_summary(eval_dir))
        return 0
    if args.stage == "judge":
        return _run_judge(args, eval_dir)
    if args.stage == "extract":
        return _run_extract(args, eval_dir)
    if args.stage in _VARIANTS:
        return _run_variant(args, eval_dir)
    return _run_effort(args, eval_dir)


if __name__ == "__main__":
    raise SystemExit(main())
