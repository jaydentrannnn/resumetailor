"""Replay the Answer book's stored AI choices under the current resolver prompt and check.

Every choice question the autofill model answered before (`answer_memory` rows with
source 'ai') is put to the model again in batches, with the installed app's profile,
resume skills and Fill model, the way `hybrid_resolver` asks it on a page. Each answer is
then run through `_usable` and `resolver_basis.supported`; the report counts what would
be applied and what would be left for the applicant, by cited basis.

The installed app's workspace is read only (SQLite ``mode=ro``; no helper that imports or
migrates is called). Values are never printed, except ``--sample`` accepted answers for a
blind check against the profile, and never for a self-identification or credential
question (`answer_memory.is_sensitive`).

    python scripts/evals/resolver_replay.py --count-only
    python scripts/evals/resolver_replay.py --sample 20
"""

from __future__ import annotations

import argparse
import collections
import json
import os
import random
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from notice_eval import app_heavy_spec  # noqa: E402

from resume_tailor import config  # noqa: E402
from resume_tailor.apply.answers import (  # noqa: E402
    answer_memory,
    hybrid_resolver,
    resolver_basis,
    resolver_types,
)
from resume_tailor.apply.answers.profile import ApplicantProfile  # noqa: E402
from resume_tailor.apply.funnel import packet_fields  # noqa: E402
from resume_tailor.apply.funnel.packet_models import Packet  # noqa: E402
from resume_tailor.content.data import MasterResume  # noqa: E402

WORKSPACE = (Path(os.environ.get("LOCALAPPDATA", "")) / "ResumeTailorData" / "data"
             / "workspaces" / "default")
_TYPES = {"select_combobox": "combobox", "choose_radio": "radiogroup",
          "check_options": "checkboxgroup"}


def stored_questions(db: Path) -> tuple[list[dict], dict[str, str]]:
    """(the AI-answered choice questions, the custom answers), read only."""
    conn = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True)
    try:
        rows = conn.execute(
            "SELECT label, action, options FROM answer_memory "
            "WHERE kind = 'answer' AND source = 'ai' ORDER BY id"
        ).fetchall()
        custom = conn.execute(
            "SELECT label, answer FROM answer_memory WHERE kind = 'answer' AND source = 'custom'"
        ).fetchall()
    finally:
        conn.close()
    seen: set[tuple] = set()
    fields = []
    for label, action, options in rows:
        options = [str(option) for option in json.loads(options or "[]")]
        key = (str(label), str(action), tuple(sorted(options)))
        if action not in _TYPES or not options or key in seen:
            continue
        seen.add(key)
        fields.append({"type": _TYPES[action], "selector": f"#q{len(fields)}",
                       "label": str(label), "options": options})
    return fields, {str(label): str(answer) for label, answer in custom}


def _basis_value(action, profile: dict, packet: Packet) -> str:
    key = action.basis_key.strip()
    if action.basis_kind == "resume":
        return "listed skill" if key in packet.master_skills else "not a listed skill"
    if action.basis_kind == "no_effect":
        return "-"
    facts = packet.fields if action.basis_kind == "packet" else profile
    value = resolver_basis._lookup(facts, key)  # noqa: SLF001
    return json.dumps(value)[:80]


def why_rejected(action, field: dict, profile: dict, packet: Packet) -> str:
    """Which part of `resolver_basis.supported` failed (no values)."""
    question = resolver_basis._question(field)  # noqa: SLF001
    if action.basis_kind not in {"profile", "packet"}:
        return f"basis {action.basis_kind}"
    key, value, custom = resolver_basis._fact(  # noqa: SLF001
        action, question, profile=profile, packet_fields=packet.fields,
    )
    if not value:
        return f"no value for {action.basis_key!r}"
    if not custom and not resolver_basis._about(key, question):  # noqa: SLF001
        match = resolver_basis.questions.classify(question)
        return f"not about {key!r} (keyed {match.key if match else None!r})"
    return f"option does not say {key!r}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--workspace", type=Path, default=WORKSPACE)
    parser.add_argument("--batch", type=int, default=12)
    parser.add_argument("--limit", type=int, default=0, help="replay only the first N")
    parser.add_argument("--sample", type=int, default=0, help="accepted answers to print")
    parser.add_argument("--seed", type=int, default=17)
    parser.add_argument("--count-only", action="store_true")
    parser.add_argument("--why", action="store_true", help="print each rejection's reason")
    args = parser.parse_args(argv)

    fields, custom = stored_questions(args.workspace / "app.db")
    if args.limit:
        fields = fields[:args.limit]
    print(f"{len(fields)} distinct stored choice questions; {len(custom)} custom answers")
    if args.count_only:
        return 0
    profile = ApplicantProfile.model_validate_json(
        (args.workspace / "applicant_profile.json").read_text(encoding="utf-8")
    )
    resume = MasterResume.model_validate_json(
        (args.workspace / "master_resume.json").read_text(encoding="utf-8")
    )
    packet = Packet.model_construct(
        fields=packet_fields.build_fields(profile, resume),
        master_skills=list(dict.fromkeys(item for group in resume.skills for item in group.items)),
    )
    safe_profile = profile.model_dump(exclude={"workday_password", "workday_email"}, mode="json")
    safe_profile["custom_answers"] = safe_profile.get("custom_answers") or custom
    resolver = hybrid_resolver._StepResolver(  # noqa: SLF001
        None, packet, profile, max_retries=1, on_progress=print, deadline=None,
        ledger=resolver_types.StepLedger(), only_invalid=False,
    )

    tally: collections.Counter = collections.Counter()
    accepted: list[tuple[dict, resolver_types.FieldAction]] = []
    with config.pinned(app_heavy_spec()):
        for start in range(0, len(fields), args.batch):
            batch = fields[start:start + args.batch]
            resolution = resolver._call_model(batch, [], safe_profile)  # noqa: SLF001
            if resolution is None:
                tally["call failed"] += len(batch)
                continue
            by_selector = {field["selector"]: field for field in batch}
            answered = set()
            for action in resolution.actions:
                field = by_selector.get(action.selector)
                if field is None or action.selector in answered:
                    continue
                answered.add(action.selector)
                if action.value.strip().casefold() == "unknown":
                    tally["unknown (left for the applicant)"] += 1
                elif not hybrid_resolver._usable(action, field):  # noqa: SLF001
                    tally["not a listed option"] += 1
                elif resolver_basis.supported(action, field, profile=safe_profile,
                                              packet_fields=packet.fields,
                                              skills=packet.master_skills):
                    tally[f"applied ({action.basis_kind})"] += 1
                    accepted.append((field, action))
                else:
                    tally[f"rejected by the check ({action.basis_kind})"] += 1
                    if args.why:
                        print(f"  x {field['label'][:90]!r}: "
                              f"{why_rejected(action, field, safe_profile, packet)}")
            tally["left out by the model"] += len(batch) - len(answered)
            print(f"  {min(start + args.batch, len(fields))}/{len(fields)} asked")
    for name, count in sorted(tally.items()):
        print(f"{name}: {count}")
    hidden = answer_memory._EEO_KEYS | {"eeo"}  # noqa: SLF001
    shown = [(field, action) for field, action in accepted
             if not answer_memory.is_sensitive(field["label"])
             and resolver_basis._PACKET_FIELD.get(  # noqa: SLF001
                 action.basis_key, action.basis_key).split(".")[0] not in hidden]
    print(f"{len(accepted) - len(shown)} applied self-identification answer(s) not shown")
    for field, action in random.Random(args.seed).sample(shown, min(args.sample, len(shown))):
        basis = _basis_value(action, safe_profile, packet)
        print(f"- {field['label'][:110]!r} -> {action.value!r} "
              f"[{action.basis_kind}: {action.basis_key} = {basis}]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
