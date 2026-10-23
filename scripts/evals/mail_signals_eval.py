"""Score `mail_signals.classify` against hand-labelled job emails (eval-only, no network).

The corpus is the student's own mail and never enters the repository: a JSONL file of
``{"message_id", "sender", "subject", "date", "body"}`` rows (for example dumped from an
Outlook PST), and a labels JSON of ``{message key: signal}`` for every email whose label
is a signal. A key is the Message-ID, else ``date|subject|sender``. Unlabelled emails
count as "nothing happened". Prints precision and recall per signal, then the dates and
subjects of every wrong and missed email so each can be read.

    python -I scripts/evals/mail_signals_eval.py --mail dump.jsonl --labels labels.json
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from resume_tailor.apply.funnel import mail_signals  # noqa: E402

_SIGNALS = ("rejected", "offer", "interview_invited", "assessment", "sent")


def key(row: dict) -> str:
    return row.get("message_id") or f"{row.get('date')}|{row.get('subject')}|{row.get('sender')}"


def load(paths: list[str]) -> list[dict]:
    rows, seen = [], set()
    for path in paths:
        # Not splitlines(): it also splits on U+2028 inside a JSON string.
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                row = json.loads(line)
                if (k := key(row)) not in seen:
                    seen.add(k)
                    rows.append(row)
    return rows


def score(rows: list[dict], labels: dict[str, str]) -> tuple[dict, dict]:
    """Per signal: (true positives, false positives, false negatives) and the rows."""
    tally = {s: Counter() for s in _SIGNALS}
    wrong: dict[str, list[tuple[str, str, str]]] = {s: [] for s in _SIGNALS}
    for row in rows:
        want = labels.get(key(row))
        got = mail_signals.classify(row.get("subject", ""), row.get("body", ""))
        for signal in _SIGNALS:
            if got == signal and want == signal:
                tally[signal]["tp"] += 1
            elif got == signal:
                tally[signal]["fp"] += 1
                wrong[signal].append(("wrong", (row.get("date") or "")[:10], row["subject"]))
            elif want == signal:
                tally[signal]["fn"] += 1
                wrong[signal].append((f"missed ({got})", (row.get("date") or "")[:10],
                                      row["subject"]))
    return tally, wrong


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--mail", nargs="+", required=True)
    parser.add_argument("--labels", required=True)
    parser.add_argument("--quiet", action="store_true", help="numbers only, no subjects")
    args = parser.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    rows = load(args.mail)
    labels = json.loads(Path(args.labels).read_text(encoding="utf-8"))
    tally, wrong = score(rows, labels)
    print(f"{len(rows)} emails, {len(labels)} labelled")
    for signal in _SIGNALS:
        t = tally[signal]
        precision = t["tp"] / (t["tp"] + t["fp"]) if t["tp"] + t["fp"] else 1.0
        recall = t["tp"] / (t["tp"] + t["fn"]) if t["tp"] + t["fn"] else 1.0
        print(f"  {signal:18s} right {t['tp']:4d}  wrong {t['fp']:3d}  missed {t['fn']:3d}"
              f"  precision {precision:6.1%}  recall {recall:6.1%}")
    if not args.quiet:
        for signal in _SIGNALS:
            for kind, day, subject in sorted(wrong[signal], key=lambda w: (w[0], w[1])):
                print(f"{signal[:9]:9s} {kind:22s} {day} {subject[:90]}")


if __name__ == "__main__":
    main()
