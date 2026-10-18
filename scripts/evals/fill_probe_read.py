"""`fill_probe.py read-only`, one target: what the fill would understand on a live form,
typing nothing. Run in a child process whose environment points every app path at a
throwaway sandbox (`fill_probe.sandbox_env`).

    fill_probe_read.py <out_dir> <port> <tag> <url> <ats> [--capture]
"""

from __future__ import annotations

import contextlib
import json
import sys
import time
import traceback
from collections import Counter
from importlib import resources
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

import capture_form  # noqa: E402
import fill_probe_data as synth  # noqa: E402
import fill_probe_guard  # noqa: E402
from notice_eval import app_heavy_spec  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402

from resume_tailor import config  # noqa: E402
from resume_tailor.apply.answers import answer, education, page_blockers, questions  # noqa: E402
from resume_tailor.apply.ats import ats_hints  # noqa: E402
from resume_tailor.apply.discovery import fetch_jd, identity  # noqa: E402
from resume_tailor.apply.forms import (  # noqa: E402
    field_catalog,
    field_matcher,
    fill_buttons,
    fill_page,
    wizards,
)
from resume_tailor.apply.forms.field_types import FieldObservation  # noqa: E402
from resume_tailor.apply.funnel import packet_fields  # noqa: E402

try:  # absent from the frozen baseline: there the probe makes that version's decisions
    from resume_tailor.apply.ats import ats_fingerprint  # noqa: E402
except ImportError:
    ats_fingerprint = None

#: Counts of widget shapes on the page, through open shadow roots.
CENSUS_JS = r"""() => {
  const vis = e => !!(e && (e.offsetWidth || e.offsetHeight || e.getClientRects().length));
  const all = [];
  const walk = root => {
    for (const el of root.querySelectorAll('*')) {
      all.push(el);
      if (el.shadowRoot) walk(el.shadowRoot);
    }
  };
  walk(document);
  const count = pred => all.filter(e => vis(e) && pred(e)).length;
  const tag = e => e.tagName.toLowerCase();
  return {
    shadow_roots: all.filter(e => e.shadowRoot).length,
    custom_elements: [...new Set(all.filter(e => tag(e).includes('-')).map(tag))].slice(0, 25),
    native_inputs: count(e => tag(e) === 'input'
      && !['hidden', 'submit', 'button', 'image', 'reset'].includes((e.type || '').toLowerCase())),
    native_selects: count(e => tag(e) === 'select'),
    textareas: count(e => tag(e) === 'textarea'),
    role_combobox: count(e => e.getAttribute('role') === 'combobox'),
    haspopup_listbox: count(e => e.getAttribute('aria-haspopup') === 'listbox'),
    file_inputs: all.filter(e => tag(e) === 'input' && e.type === 'file').length,
    iframes: [...document.querySelectorAll('iframe')]
      .map(f => (f.src || '').split('?')[0].slice(0, 80)).slice(0, 8),
    captcha: !!document.querySelector("iframe[src*='recaptcha'], iframe[src*='hcaptcha'], "
      + ".g-recaptcha, .h-captcha, iframe[src*='turnstile'], .cf-turnstile"),
    password_inputs: count(e => tag(e) === 'input' && e.type === 'password'),
    url: location.href,
  };
}"""


def _settle(page: Any, ms: int) -> None:
    with contextlib.suppress(Exception):
        page.wait_for_load_state("networkidle", timeout=10000)
    page.wait_for_timeout(ms)


def _scan(page: Any, fields: dict, hints: dict) -> tuple[list[dict], list[str]]:
    filler_js = fill_page._load_filler_js()
    args = {
        "fields": fields,
        "hints": hints,
        "synonyms": fill_page._synonym_payload(),
        "eeo": field_matcher.eeo_patterns(fields),
        "educationAliases": education.LEVEL_BY_ALIAS,
        "scan": True,
    }
    scanned, errors = [], []
    for index, frame in enumerate(page.frames):
        try:
            res = frame.evaluate(filler_js, args)
        except Exception as exc:  # noqa: BLE001 - cross-origin or navigating frames
            errors.append(f"{index}:{type(exc).__name__}")
            continue
        for q in (res or {}).get("questions") or []:
            scanned.append({**q, "_frame": index})
    return scanned, errors


def _verified_scan(page: Any) -> dict:
    script = (
        resources.files("resume_tailor.apply.driver")
        .joinpath("dom_scan.js")
        .read_text(encoding="utf-8")
    )
    policies: Counter[str] = Counter()
    for frame in page.frames:
        with contextlib.suppress(Exception):
            for item in (frame.evaluate(script) or {}).get("fields") or []:
                item.pop("selector", None)
                item.update(
                    snapshot_id="p",
                    field_id=str(sum(policies.values())),
                    frame_id="f",
                    document_generation="1",
                )
                with contextlib.suppress(Exception):
                    policy, _key = field_catalog.classify(FieldObservation.model_validate(item))
                    policies[policy] += 1
    return dict(policies)


def _screens(ats: str) -> wizards.WizardAdapter:
    """The screen check a fill of this code version uses (`wizards.for_fill`)."""
    for_fill = getattr(wizards, "for_fill", None)
    if for_fill is not None:
        return for_fill(ats)
    return wizards.for_ats(ats) or wizards.WizardAdapter()


def _landed(page: Any, ats: str) -> tuple[str, str]:
    """(landed platform, the ATS the fill switches to), as `fill_entry._recheck_platform`."""
    if ats_fingerprint is None:
        return "", ats
    platform = ats_fingerprint.page_platform(page)
    stored = ats_fingerprint.stored_ats(platform) if platform else None
    if stored in {None, "other", "unknown", ats.lower()}:
        return platform, ats
    return platform, stored


def probe(
    page: Any, ctx: Any, target: dict, fields: dict, facts: Any, out: Path, capture: bool
) -> dict:
    """The entry decisions a fill makes (`fill_entry._open_form`, `fill_wizard._wizard_gate`),
    typing nothing: open the posting, press Apply off Workday, re-check the platform, and
    open a platform's form from its posting page."""
    report: dict[str, Any] = {"tag": target["tag"], "url": target["url"]}
    started = time.monotonic()
    ats = target["ats"] or fetch_jd.detect_ats(target["url"])
    report["detected_ats"] = ats
    screens = _screens(ats)
    response = page.goto(target["url"], wait_until="domcontentloaded", timeout=60000)
    report["http_status"] = getattr(response, "status", None)
    _settle(page, 1500)
    lost = getattr(identity, "lost_posting", None)
    report["lost_posting"] = bool(lost and lost(target["url"], str(page.url)))
    report["state_before"] = screens.detect_state(page)
    if ats != "workday":
        with contextlib.suppress(Exception):
            page = fill_buttons.find_and_click_apply(page, ats, context=ctx)
        _settle(page, 2500)
    report["landed_platform"], landed = _landed(page, ats)
    if landed != ats:
        ats, screens = landed, _screens(landed)
    report["fill_ats"] = ats
    state = screens.detect_state(page)
    if state == "posting" and screens.enter(page):
        _settle(page, 3000)
        state = screens.detect_state(page)
    report["state_after"] = state
    report["after"] = page.evaluate(CENSUS_JS)
    report["final_url"] = page.url
    if capture:
        for index, frame in enumerate(page.frames):
            with contextlib.suppress(Exception):
                name = "page" if index == 0 else f"frame{index}"
                capture_form.capture(frame, out / "captures" / f"{target['tag']}.{name}.html")

    scanned, report["frame_errors"] = _scan(page, fields, ats_hints.hints_for(ats))
    rules = questions.plan_for(scanned, facts)
    asked: list = []

    def classifier(batch: list) -> Any:
        asked.append(len(batch))
        return answer.classify_questions(batch)

    with_model = questions.plan_for(scanned, facts, classifier=classifier)
    report["questions"] = [
        {
            "label": (q.get("label") or "")[:160],
            "kind": q.get("kind"),
            "required": q.get("required"),
            "options": len(q.get("options") or []),
            "rule_key": (rules.get(q.get("qid")) or {}).get("key"),
            "model_key": (with_model.get(q.get("qid")) or {}).get("key"),
        }
        for q in scanned
    ]
    report["model_asked"] = sum(asked)
    report["model_asked_batches"] = len(asked)
    report["dom_scan"] = {"policies": _verified_scan(page)}
    blockers = page_blockers.extract_page_blockers(page)
    report["blockers"] = {
        "errors": len(blockers.get("errors") or []),
        "unresolved": [
            (b.get("type"), (b.get("label") or "")[:80]) for b in blockers.get("unresolved") or []
        ][:40],
    }
    report["advance_button"] = fill_buttons._find_advance_button(page) is not None
    report["submit_button"] = fill_buttons._find_submit_button(page, {}) is not None
    report["seconds"] = round(time.monotonic() - started, 1)
    with contextlib.suppress(Exception):
        page.screenshot(path=str(out / f"{target['tag']}.png"), full_page=True)
    return report


def run_one(target: dict, out: Path, port: int, *, capture: bool) -> None:
    fields = packet_fields.build_fields(synth.PROFILE, synth.RESUME)
    facts = questions.facts_for(fields)
    audit = fill_probe_guard.Audit(out / f"{target['tag']}.requests.jsonl")
    with sync_playwright() as p, config.pinned(app_heavy_spec()):
        browser = p.chromium.connect_over_cdp(f"http://127.0.0.1:{port}")
        ctx = browser.contexts[0]
        fill_probe_guard.install(ctx, audit, synth.MARKERS, synth.ANSWER_MARKERS)
        page = ctx.new_page()
        page.set_default_timeout(10000)
        try:
            report = probe(page, ctx, target, fields, facts, out, capture)
        except Exception:  # noqa: BLE001
            report = {
                "tag": target["tag"],
                "url": target["url"],
                "error": traceback.format_exc()[-1500:],
            }
    audit.close()
    report["audit"] = audit.summary()
    (out / f"{target['tag']}.json").write_text(json.dumps(report, indent=1), encoding="utf-8")
    print(
        "done",
        target["tag"],
        report.get("seconds"),
        report.get("state_after"),
        len(report.get("questions") or []),
        flush=True,
    )


if __name__ == "__main__":
    out_dir, port_arg, tag, url, ats = sys.argv[1:6]
    run_one(
        {"tag": tag, "url": url, "ats": ats},
        Path(out_dir),
        int(port_arg),
        capture="--capture" in sys.argv[6:],
    )
