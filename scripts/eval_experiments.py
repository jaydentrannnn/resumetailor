"""Experiments E1 (cosmetic polish on frozen drafts) and E2 (narrow anti-invention clause),
then the end-to-end confirmation of whatever passes.

Every arm runs on the profile's Light model at its production effort, against a sandbox
copy of the desktop app's data (`evals/sandbox.py`). Commands resume: a rerun skips
finished tasks and judged pairs.

    python scripts\\eval_experiments.py drafts --limit 40      # frozen first drafts
    python scripts\\eval_experiments.py polish                 # medium, none, low on them
    python scripts\\eval_experiments.py clause                 # fresh drafts + the clause
    python scripts\\eval_experiments.py judge
    python scripts\\eval_experiments.py report --look 1
    python scripts\\eval_experiments.py drafts --extend 40     # only on CONTINUE; rerun all

End to end (process-isolated workers; baseline first so caches are shared):

    python scripts\\eval_experiments.py e2e --arm base --limit 20
    python scripts\\eval_experiments.py e2e --arm ship --polish none --clause --limit 20
    python scripts\\eval_experiments.py e2e-judge --arm ship
    python scripts\\eval_experiments.py e2e-report --arm ship
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from evals import corpus, sandbox  # noqa: E402  (no resume_tailor imports yet)

EVAL_DIR = ROOT / "output" / "eval" / os.environ.get("EVAL_NAME", "polish-clause")
E2E_DIR = EVAL_DIR / "e2e"
#: Another eval whose sandbox (same resume, templates and caches) and cases this one
#: reuses, so a second model is measured on exactly the first one's inputs.
SOURCE_DIR = (ROOT / "output" / "eval" / os.environ["EVAL_FROM"]
              if os.environ.get("EVAL_FROM") else None)
os.environ.update(sandbox.environment(sandbox.prepare(
    EVAL_DIR, *([SOURCE_DIR / "sandbox"] if SOURCE_DIR else []))))

from evals import arms as arms_mod  # noqa: E402
from evals import e2e, judge, report, report_seq, sequential, survey, variants  # noqa: E402
from evals.stages import Replay  # noqa: E402

JUDGE_MODEL = os.environ.get("JUDGE_MODEL", "gemini-4-argon")
PAIRS = {"e1": [(report_seq.BASE, "polish-none#0"), (report_seq.BASE, "polish-low#0")],
         "e2": [(report_seq.BASE, "clause#0")],
         "polish": [(survey.POLISHED, survey.UNPOLISHED)]}


def _meta() -> dict:
    path = EVAL_DIR / "meta.json"
    return json.loads(path.read_text("utf-8")) if path.exists() else {}


def _save_meta(meta: dict) -> None:
    (EVAL_DIR / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")


def _progress(record: dict) -> None:
    note = record.get("error", "")[:160] if record["status"] == "error" else (
        f"{record['usage']['wall_ms'] / 1000:.1f}s")
    print(f"  {record['status']:5} {record['key']}  {note}", flush=True)


def _cases(replay: Replay, meta: dict) -> list:
    by_id = {c.case_id: c for c in corpus.load_saved(sandbox.live_jobs_dir("default"), "default")}
    return [by_id[c] for c in meta["cases"] if c in by_id]


def _results() -> arms_mod.Results:
    return arms_mod.Results(EVAL_DIR / "cases.jsonl")


def _model(spec) -> str:
    return spec["model"] if isinstance(spec, dict) else str(spec)


def cmd_drafts(args, replay: Replay) -> None:
    meta = _meta()
    eligible = [c for c in corpus.load_saved(sandbox.live_jobs_dir("default"), "default")
                if replay.can_rewrite(c)]
    if not meta:
        commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True,
                                text=True, check=True).stdout.strip()
        if SOURCE_DIR is not None:
            by_id = {c.case_id: c for c in eligible}
            source = json.loads((SOURCE_DIR / "meta.json").read_text("utf-8"))["cases"]
            chosen = [by_id[c] for c in source[: args.limit] if c in by_id]
        else:
            chosen = corpus.sample(eligible, args.limit, seed=args.seed)
        meta = {"commit": commit, "seed": args.seed, "model": _model(replay.light_spec),
                "spec": replay.light_spec, "judge_model": JUDGE_MODEL,
                "cases": [c.case_id for c in chosen], "look1": len(chosen)}
    if SOURCE_DIR is not None and args.limit > len(meta["cases"]):
        # A smoke run of a few cases grows to the full sample, in the source's order.
        by_id = {c.case_id: c for c in eligible}
        source = json.loads((SOURCE_DIR / "meta.json").read_text("utf-8"))["cases"]
        meta["cases"] = [c for c in source[: args.limit] if c in by_id]
        meta["look1"] = len(meta["cases"])
    if args.extend and len(meta["cases"]) == meta["look1"]:
        rest = [c for c in eligible if c.case_id not in set(meta["cases"])]
        meta["cases"] += [c.case_id for c in corpus.sample(rest, args.extend, seed=args.seed)]
    _save_meta(meta)
    cases = _cases(replay, meta)
    print(f"{len(cases)} case(s) of {len(eligible)} eligible on {meta['model']}; "
          f"baseline {meta['commit'][:10]}")
    arm = arms_mod.Arm("draft", replay.light_spec)
    arms_mod.run([(c, arm) for c in cases], replay.prepolish, _results(),
                 setup=replay.setup, workers=args.workers, out_dir=EVAL_DIR, progress=_progress)


def cmd_polish(args, replay: Replay) -> None:
    meta = _meta()
    drafts = report.by_arm(_results().records()).get("draft#0", {})
    cases = [c for c in _cases(replay, meta) if c.case_id in drafts]
    for effort in args.efforts.split(","):
        def stage(case, effort=effort):
            # "default" is the stage's production effort for this model.
            return replay.polish(case, drafts[case.case_id]["result"],
                                 None if effort == "default" else effort)
        arm = arms_mod.Arm(f"polish-{effort}", replay.light_spec)
        arms_mod.run([(c, arm) for c in cases], stage, _results(), setup=replay.setup,
                     workers=args.workers, out_dir=EVAL_DIR, progress=_progress)


def cmd_clause(args, replay: Replay) -> None:
    def stage(case):
        with variants.clause():
            return replay.rewrite(case)
    arm = arms_mod.Arm("clause", replay.light_spec)
    arms_mod.run([(c, arm) for c in _cases(replay, _meta())], stage, _results(),
                 setup=replay.setup, workers=args.workers, out_dir=EVAL_DIR, progress=_progress)


def cmd_rescore(args, replay: Replay) -> None:
    """Recompute every finished record's metrics from its stored texts after a metric
    change: no model calls. The previous file is kept as `cases.jsonl.bak`."""
    from resume_tailor import config
    from resume_tailor.infra import atomic

    path = EVAL_DIR / "cases.jsonl"
    by_id = {c.case_id: c for c in _cases(replay, _meta())}
    lines, changed = [], 0
    for r in _results().records():
        res = r.get("result") or {}
        if r.get("status") == "ok" and r["case"] in by_id and "texts" in res:
            case = by_id[r["case"]]
            with config.use_context(config.context_for_workspace(case.workspace)):
                replay.setup(case)
                fresh = replay._rewrite_record(case, res["texts"], res["fabrications_rejected"],
                                               res.get("verbs_diversified", 0))
            changed += fresh["metrics"] != res.get("metrics")
            res["metrics"], res["must"] = fresh["metrics"], fresh["must"]
        lines.append(json.dumps(r, ensure_ascii=False))
    shutil.copy2(path, path.with_name("cases.jsonl.bak"))
    atomic.write_text(path, "\n".join(lines) + "\n")
    print(f"rescored {len(lines)} record(s); {changed} changed")


def judge_spec(replay: Replay) -> dict:
    spec = dict(replay.profile_spec)
    spec["model"] = JUDGE_MODEL
    spec.pop("base_url", None)
    spec["vertex_location"] = os.environ.get("JUDGE_LOCATION", "global")
    return spec


def _judge(jobs: list, replay: Replay, eval_dir: Path, workers: int) -> None:
    verdicts = judge.Verdicts(judge.verdicts_file(eval_dir))
    done = {r["key"] for r in verdicts.records() if "winner" in r}
    todo = []
    for job in jobs:
        case, a, b, _build, out_a, out_b = job
        key = f"{case}|{a}|{b}"
        if key in done:
            continue
        if out_a == out_b:  # nothing to judge: identical outputs are a tie by definition
            verdicts.append({"key": key, "case": case, "a": a, "b": b, "winner": "tie",
                             "consistent": True, "identical": True, "reasons": []})
        else:
            todo.append(job)
    spec = judge_spec(replay)
    print(f"{len(todo)} pair(s) to judge on {spec['model']} ({len(jobs) - len(todo)} done "
          "or identical)")
    judge.run(todo, "rewrite", spec, verdicts, workers=workers, progress=lambda r: print(
        f"  {r.get('winner', 'error'):5} {r['key']} {r.get('error', '')[:160]}", flush=True))


def cmd_judge(args, replay: Replay) -> None:
    grouped = report.by_arm(_results().records())
    by_id = {c.case_id: c for c in _cases(replay, _meta())}
    jobs = []
    for a, b in [p for name in args.pairs.split(",") for p in PAIRS[name]]:
        for cid in sorted(set(grouped.get(a, {})) & set(grouped.get(b, {})) & set(by_id)):
            build, out_a, out_b = replay.judge_inputs(
                "rewrite", by_id[cid], grouped[a][cid]["result"], grouped[b][cid]["result"])
            jobs.append((cid, a, b, build, out_a, out_b))
    _judge(jobs, replay, EVAL_DIR, args.workers)


def cmd_report(args, _replay=None) -> None:
    meta = _meta()
    cases = meta["cases"][: meta["look1"]] if args.look == 1 else meta["cases"]
    grouped = report.by_arm(_results().records())
    verdicts = judge.Verdicts(judge.verdicts_file(EVAL_DIR)).records()
    text = report_seq.markdown(grouped, verdicts, cases, args.look, meta["model"], meta)
    (EVAL_DIR / f"summary.look{args.look}.md").write_text(text, encoding="utf-8")
    print(text)


# -- end to end ----------------------------------------------------------------------------


def _e2e_cases(replay: Replay, limit: int) -> list:
    return _cases(replay, _meta())[:limit]


def cmd_e2e(args, _replay=None) -> None:
    env = {variants.CLAUSE_ENV: "1" if args.clause else "0",
           variants.POLISH_ENV: args.polish or ""}
    meta = _meta()
    meta.setdefault("e2e", {})[args.arm] = {"clause": args.clause, "polish": args.polish}
    _save_meta(meta)
    command = e2e.worker_command(Path(__file__), "e2e-worker", "--arm", args.arm,
                                 "--limit", str(args.limit))
    bad = e2e.launch(command, env, args.workers)
    print(f"{args.arm}: {len(e2e.load(E2E_DIR, args.arm))} record(s); {bad} worker(s) failed")


def cmd_e2e_worker(args, replay: Replay) -> None:
    cases = [(c.case_id, c.jd_text) for c in _e2e_cases(replay, args.limit)]
    e2e.run_worker(E2E_DIR, args.arm, cases, spec=replay.light_spec, effort=None)


def cmd_e2e_judge(args, replay: Replay) -> None:
    # `--ref ship` judges against the source eval's arm (a survey's reference model).
    ref_dir = SOURCE_DIR / "e2e" if args.ref and SOURCE_DIR else E2E_DIR
    base, cand = e2e.load(ref_dir, args.ref or "base"), e2e.load(E2E_DIR, args.arm)
    jobs = []
    for case in _e2e_cases(replay, args.limit):
        a, b = base.get(case.case_id), cand.get(case.case_id)
        if not a or not b or "bullets" not in a or "bullets" not in b:
            continue
        # Judge the bullets both pages carry; selection differences are gated separately.
        ids = sorted(set(a["bullets"]) & set(b["bullets"]) & set(replay.by_id))
        requirements = replay._requirements(case)
        must = [k.phrase for k in requirements.keywords if k.importance == "must_have"]
        build = judge.rewrite_prompt(requirements.title, must, replay.judge_sources(ids))
        jobs.append((case.case_id, "base", args.arm, build,
                     {i: a["bullets"][i] for i in ids}, {i: b["bullets"][i] for i in ids}))
    _judge(jobs, replay, E2E_DIR, args.workers)


def cmd_e2e_report(args, _replay=None) -> None:
    meta = _meta()
    base, cand = e2e.load(E2E_DIR, "base"), e2e.load(E2E_DIR, args.arm)
    verdicts = judge.Verdicts(judge.verdicts_file(E2E_DIR)).records()
    scores = sequential.case_scores(verdicts, "base", args.arm)
    cases = meta["cases"][: args.limit]
    rows = e2e.gates(cases, base, cand, scores, model=meta["model"], cost_limit=0.10)
    lines = [f"# End to end: base vs {args.arm} ({meta.get('e2e', {}).get(args.arm)})", "",
             "| Gate | Detail | Result |", "|---|---|---|"]
    lines += [f"| {g} | {d} | {'pass' if ok else 'FAIL'} |" for g, d, ok in rows]
    lines += ["", f"**{'SHIP' if all(ok for *_, ok in rows) else 'BLOCKED'}**", "",
              f"Runtime: base {e2e.runtime(base)}, {args.arm} {e2e.runtime(cand)}."]
    text = "\n".join(lines) + "\n"
    (E2E_DIR / f"summary.{args.arm}.md").write_text(text, encoding="utf-8")
    print(text)


def cmd_polish_report(args, _replay=None) -> None:
    meta = _meta()
    text = survey.polish_markdown(report.by_arm(_results().records()),
                                  judge.Verdicts(judge.verdicts_file(EVAL_DIR)).records(),
                                  meta["cases"], meta["model"])
    (EVAL_DIR / "summary.polish.md").write_text(text, encoding="utf-8")
    print(text)


def cmd_survey_report(args, _replay=None) -> None:
    dirs = [ROOT / "output" / "eval" / name for name in args.evals.split(",")]
    text = survey.survey_markdown(dirs)
    (ROOT / "output" / "eval" / "survey-summary.md").write_text(text, encoding="utf-8")
    print(text)


COMMANDS = {"rescore": cmd_rescore, "drafts": cmd_drafts, "polish": cmd_polish,
            "clause": cmd_clause, "judge": cmd_judge, "report": cmd_report, "e2e": cmd_e2e,
            "e2e-worker": cmd_e2e_worker, "e2e-judge": cmd_e2e_judge,
            "e2e-report": cmd_e2e_report, "polish-report": cmd_polish_report,
            "survey-report": cmd_survey_report}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("cmd", choices=list(COMMANDS))
    p.add_argument("--limit", type=int, default=40)
    p.add_argument("--extend", type=int, default=0)
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--workers", type=int, default=4)
    p.add_argument("--efforts", default="medium,none,low")
    p.add_argument("--pairs", default="e1,e2")
    p.add_argument("--look", type=int, default=1, choices=[1, 2])
    p.add_argument("--arm", default="base")
    p.add_argument("--polish", choices=["none", "low"], default=None)
    p.add_argument("--clause", action="store_true")
    p.add_argument("--ref", default="", help="judge e2e against this arm of EVAL_FROM")
    p.add_argument("--evals", default="", help="survey-report: comma-separated eval names")
    args = p.parse_args(argv)
    if args.cmd in {"report", "e2e", "e2e-report", "polish-report", "survey-report"}:
        COMMANDS[args.cmd](args)
        return 0
    COMMANDS[args.cmd](args, Replay("default"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
