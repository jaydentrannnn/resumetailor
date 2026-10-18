"""Score the notice detector on the labelled corpora: what would a fill agree to?

No model calls unless ``--tie-breaker`` is given. Each corpus case is a required
checkbox (or Yes/No question) whose text is the case text, offered to every path that
can tick one: ``questions.plan_for`` (a checkbox and a Yes/No choice) and the two
consent routes in ``form_routes``. A case counts as agreed when any path agrees.

- unsupported agreement: a ``fact``, ``optional`` or ``not_a_notice`` case agreed to;
- unnecessary handoff: a ``routine`` case not agreed to.

The baseline detector runs as a whole package from another source tree (a ``git
worktree`` of the commit before the detector change) in a subprocess, as in
``guard_replay.py``:

    git worktree add <tmp>/base <commit-before>
    python scripts/evals/notice_eval.py --baseline-src <tmp>/base/src

The held-out corpus is reported as aggregates only (never a case id or text): it was
written apart from the detector and must stay unseen while the detector is tuned.
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
CORPORA = {
    "dev": ROOT / "tests" / "fixtures" / "notices" / "dev.json",
    "heldout": ROOT / "tests" / "fixtures" / "notices" / "heldout.json",
}


def predict(cases: list[dict], *, tie_breaker: bool = False) -> dict[str, dict]:
    """Child mode: what the importable ``resume_tailor`` does with each case."""
    from resume_tailor.apply.answers import form_facts, questions
    from resume_tailor.apply.forms import form_routes

    facts = questions.facts_for({"auto_accept_routine_acknowledgements": "Yes"})
    verdicts: dict[str, str] = {}
    if tie_breaker:
        from resume_tailor.apply.answers import answer

        unclear = [(c["text"], "") for c in cases
                   if form_facts.acknowledgement(c["text"]) == "unclear"]
        verdicts = answer.classify_notices(unclear) if unclear else {}
    out = {}
    for case in cases:
        text = case["text"]
        items = [
            {"qid": "box", "label": text, "kind": "checkbox"},
            {"qid": "choice", "label": text, "kind": "choice", "options": ["Yes", "No"]},
        ]
        plan = questions.plan_for(items, facts, notices=lambda _pending: verdicts)
        row = {"label": text, "context": text, "required": True, "enabled": True,
               "visible": True}
        accepted, _left = form_routes.consent_candidates([row], allow_routine=True,
                                                         verdicts=verdicts)
        leftover = {"type": "checkbox", "required": True, "selector": "#box", "label": text}
        paths = {
            "checkbox": plan["box"].get("value") == "Yes",
            "choice": plan["choice"].get("value") == "Yes",
            "consent_route": bool(accepted),
            "leftover_route": form_routes.is_required_consent(leftover),
        }
        match = questions.classify(questions.Question(text, kind="choice", options=("Yes", "No")))
        out[case["id"]] = {
            "kind": form_facts.acknowledgement(text),
            "verdict": verdicts.get(form_facts.notice_key(text), ""),
            "agreed": any(paths.values()),
            "paths": [name for name, agreed in paths.items() if agreed],
            "declined": plan["box"].get("value") == "No",
            "key": match.key if match else None,
        }
    return out


def app_heavy_spec() -> object:
    """The installed app's Fill model (Apply settings' Heavy), as `config.pinned` takes it."""
    from resume_tailor.web.schemas import ApplySettings

    path = Path(os.environ["LOCALAPPDATA"]) / "ResumeTailorData" / "data" / "ai_settings.json"
    return ApplySettings(**json.loads(path.read_text(encoding="utf-8"))["apply"]).model_spec


def run_child(src: Path, corpus: Path, *, tie_breaker: bool, model: str = "") -> dict[str, dict]:
    env = {**os.environ, "PYTHONPATH": str(src)}
    args = [sys.executable, str(Path(__file__).resolve()), "--child", str(corpus)]
    if tie_breaker:
        args += ["--tie-breaker", "--model", model]
    done = subprocess.run(args, env=env, capture_output=True, text=True, encoding="utf-8",
                          check=False)
    if done.returncode:
        raise SystemExit(f"predict failed under {src}:\n{done.stderr}")
    return json.loads(done.stdout)


def score(cases: list[dict], predicted: dict[str, dict]) -> dict:
    unsupported = [c for c in cases if c["label"] != "routine" and predicted[c["id"]]["agreed"]]
    handoffs = [c for c in cases if c["label"] == "routine" and not predicted[c["id"]]["agreed"]]
    optional = [c for c in cases if c["label"] == "optional"]
    keyed = [c for c in cases if c["label"] == "fact"
             and c.get("fact_key") not in {None, "applicant", "resume"}]
    return {
        "unsupported": unsupported,
        "handoffs": handoffs,
        "declined_optional": sum(predicted[c["id"]]["declined"] for c in optional),
        "optional": len(optional),
        "key_hits": sum(predicted[c["id"]]["key"] == c["fact_key"] for c in keyed),
        "keyed": len(keyed),
        "kinds": Counter((c["label"], predicted[c["id"]]["kind"] or "-") for c in cases),
    }


def report(name: str, cases: list[dict], arms: dict[str, dict[str, dict]]) -> None:
    print(f"\n== {name}: {len(cases)} cases {dict(Counter(c['label'] for c in cases))}")
    for arm, predicted in arms.items():
        result = score(cases, predicted)
        print(f"  [{arm}] unsupported agreements {len(result['unsupported'])}"
              f" ({dict(Counter(c['label'] for c in result['unsupported']))}),"
              f" unnecessary handoffs {len(result['handoffs'])},"
              f" optional declined {result['declined_optional']}/{result['optional']}")
        if name == "heldout":
            continue  # aggregates only
        print(f"      fact keys found {result['key_hits']}/{result['keyed']}")
        for c in result["unsupported"]:
            print(f"      AGREED  {c['id']} [{c['label']}] via"
                  f" {','.join(predicted[c['id']]['paths'])}: {c['text'][:90]}")
        for c in result["handoffs"]:
            kind = predicted[c["id"]]["kind"] or "-"
            print(f"      HANDOFF {c['id']} ({kind}): {c['text'][:90]}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--baseline-src", type=Path, help="src/ of the tree to compare against")
    parser.add_argument("--corpus", choices=[*CORPORA, "all"], default="all")
    parser.add_argument("--tie-breaker", action="store_true",
                        help="resolve unclear notices with the model (current tree only)")
    parser.add_argument("--model", default="app",
                        help="spec for the tie-breaker: a profile name, JSON, or 'app' for "
                             "the installed app's Fill model (default)")
    parser.add_argument("--child", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.child:
        cases = json.loads(args.child.read_text(encoding="utf-8"))["cases"]
        if not args.tie_breaker:
            json.dump(predict(cases), sys.stdout)
            return 0
        from resume_tailor import config

        spec = (app_heavy_spec() if args.model == "app" else
                json.loads(args.model) if args.model.startswith("{") else args.model)
        with config.pinned(spec):
            json.dump(predict(cases, tie_breaker=True), sys.stdout)
        return 0
    names = list(CORPORA) if args.corpus == "all" else [args.corpus]
    for name in names:
        cases = json.loads(CORPORA[name].read_text(encoding="utf-8"))["cases"]
        arms = {}
        if args.baseline_src:
            arms["baseline"] = run_child(args.baseline_src, CORPORA[name], tie_breaker=False)
        arms["current"] = run_child(ROOT / "src", CORPORA[name], tie_breaker=False)
        if args.tie_breaker:
            arms["current+model"] = run_child(ROOT / "src", CORPORA[name], tie_breaker=True,
                                              model=args.model)
        report(name, cases, arms)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
