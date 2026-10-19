"""`scripts/evals` fill-probe pieces that run without a browser: the live probe's network
guard (`fill_probe_guard.decide`) and the fixture sanitizer (`capture_form.sanitize`)."""

from __future__ import annotations

import base64
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from evals import capture_form, fill_probe_guard  # noqa: E402

MARKERS = (b"Zyxt", b"Quorv", b"5550147", b"555-0147")
ANSWERS = (b"California State University", b"Sacramento", b"95814")
JSON = {"content-type": "application/json"}


def _decide(method: str, url: str, body: bytes = b"", headers: dict | None = None):
    return fill_probe_guard.decide(
        method, url, headers if headers is not None else JSON, body, MARKERS, ANSWERS
    )


def test_reads_lookups_and_unmarked_writes_pass():
    assert _decide("GET", "https://jobs.example.com/apply").allow
    assert _decide("GET", "https://jobs.example.com/api/geo?q=Sacramento").allow
    assert _decide("POST", "https://places.googleapis.com/v1/places:autocomplete",
                   b'{"input": "Sacramento"}').allow
    assert _decide("POST", "https://jobs.example.com/api/form", b'{"query": "{ form { id } }"}').allow


def test_a_form_save_never_leaves_whatever_it_carries():
    answers = _decide("POST", "https://jobs.example.com/api/state",
                      b'{"school": "California State University", "gpa": "3.7"}')
    autosave = _decide("PUT", "https://jobs.example.com/applications/9/autosave",
                       b'{"q1": "Yes", "gpa": "3.7"}')
    mutation = _decide("POST", "https://jobs.example.com/graphql",
                       b'{"query": "mutation SetAnswer($v: String) { set(v: $v) }"}')
    assert [d.reason for d in (answers, autosave, mutation)] == [
        "applicant answers in body", "form write", "form write",
    ]
    assert not any(d.allow for d in (answers, autosave, mutation))


def test_applicant_data_never_leaves_in_any_encoding():
    plain = _decide("POST", "https://jobs.example.com/autosave", b'{"first": "Zyxta"}')
    encoded = _decide("POST", "https://jobs.example.com/a", b"first=Zy%78ta",
                      {"content-type": "application/x-www-form-urlencoded"})
    hidden = base64.b64encode(json.dumps({"name": "Quorvel"}).encode())
    wrapped = _decide("POST", "https://t.example.net/collect", b'{"d": "' + hidden + b'"}')
    in_url = _decide("GET", "https://t.example.net/p?email=zyxta%40x&n=Zyxta")
    assert not any(d.allow for d in (plain, encoded, wrapped, in_url))
    assert all(d.marked for d in (plain, encoded, wrapped, in_url))


def test_uploads_opaque_bodies_and_recorders_are_blocked():
    upload = _decide("POST", "https://jobs.example.com/upload", b"--x\r\n",
                     {"content-type": "multipart/form-data; boundary=x"})
    gzipped = _decide("POST", "https://jobs.example.com/a", b"\x1f\x8b\x08",
                      {"content-type": "application/json", "content-encoding": "gzip"})
    binary = _decide("POST", "https://jobs.example.com/a", b"\xff\xfe\x00", {})
    recorder = _decide("POST", "https://rs.fullstory.com/rec/bundle", b'{"e": []}')
    assert [d.reason for d in (upload, gzipped, binary, recorder)] == [
        "upload", "unreadable body", "unreadable body", "session recorder",
    ]
    assert not any(d.allow for d in (upload, gzipped, binary, recorder))


def test_audit_counts_and_writes_no_query_or_body(tmp_path):
    audit = fill_probe_guard.Audit(tmp_path / "r.jsonl")
    audit.record("GET", "https://jobs.example.com/a?token=secret", 0,
                 fill_probe_guard.Decision(True, "read"))
    audit.record("POST", "https://jobs.example.com/b", 12,
                 fill_probe_guard.Decision(False, "applicant data in body", marked=True))
    audit.close()
    text = (tmp_path / "r.jsonl").read_text(encoding="utf-8")
    assert "secret" not in text
    assert audit.summary() == {
        "counts": {"allow: read": 1, "block: applicant data in body": 1},
        "allowed_with_applicant_data": 0,
        "allowed_reads_with_answers": 0,
        "allowed_writes": {},
    }


def test_the_audit_checks_every_request_apart_from_the_decision(tmp_path):
    audit = fill_probe_guard.Audit(tmp_path / "r.jsonl")
    allowed = fill_probe_guard.Decision(True, "write without applicant data")
    body = b'{"school": "California State University"}'
    identity, answered = fill_probe_guard.check("https://x.example/a", body, MARKERS, ANSWERS)
    audit.record("POST", "https://x.example/a", len(body), allowed, identity=identity, answered=answered)
    identity, answered = fill_probe_guard.check("https://x.example/geo?q=Sacramento", b"", MARKERS, ANSWERS)
    audit.record("GET", "https://x.example/geo?q=Sacramento", 0, fill_probe_guard.Decision(True, "read"),
                 identity=identity, answered=answered)
    audit.close()
    summary = audit.summary()
    assert summary["allowed_with_applicant_data"] == 1  # a decision that let it through is caught
    assert summary["allowed_reads_with_answers"] == 1
    assert summary["allowed_writes"] == {"POST x.example/a": 1}


RAW = """<!doctype html><html><head><meta charset="utf-8"><title>Acme Robotics careers</title>
<script>window.__STATE__ = {"email": "jane@corp.com"}</script>
<script type="application/json">{"token": "abc"}</script><link rel="stylesheet" href="/a.css?v=1"></head>
<body><!-- served for jane@corp.com -->
<form action="/apply?session=xyz"><label for="e">Email</label>
<input id="e" type="email" value="jane@corp.com"><input type="hidden" name="csrf" value="tok123">
<label><input type="radio" name="y" value="Yes" checked>Yes</label>
<select><option selected>Acme Robotics HQ</option></select>
<textarea>my cover letter</textarea><div contenteditable="true">draft</div>
<p>Call (916) 555-0199 or upload Jane_Doe_Resume.pdf. Acme Robotics is an equal opportunity employer.</p>
<a href="https://acme.example/jobs/1?utm=x" onclick="track()">Job</a>
<my-widget><template shadowrootmode="open"><span>Acme Robotics widget</span></template></my-widget>
</form></body></html>"""


def test_sanitize_strips_values_scripts_queries_names_and_contact_details():
    clean = capture_form.sanitize(RAW, {"Acme Robotics": "Example Co"})
    for gone in ("jane@corp.com", "tok123", "__STATE__", "token", "session=xyz", "utm=x", "a.css",
                 "my cover letter", "draft", "555-0199", "Jane_Doe_Resume", "Acme", "onclick",
                 "checked", "selected"):
        assert gone not in clean, gone
    assert "Example Co is an equal opportunity employer" in clean
    assert 'value="Yes"' in clean  # an option's own value is not an answer
    assert 'shadowrootmode="open"' in clean
    assert capture_form.leaks(clean) == []


def test_leaks_names_what_is_left():
    assert capture_form.leaks('<a href="/x?y=1">a</a> bob@corp.com 916-555-0199') == [
        "email", "phone", "url query",
    ]


WIDGETS = """<div data-applicant='{"name": "Jane Roe", "street": "12 Elm Rd"}' data-qa="name-field">
<div class="select__single-value">Jane Roe's school</div>
<div class="select__multi-value"><span class="chip">Elm Rd volunteer</span></div>
<div role="combobox" aria-valuetext="Lisbon">Lisbon</div>
<ul role="listbox"><li role="option" aria-selected="true">Option A</li><li role="option">Option B</li></ul>
<p>Lives near Sacramento; studied at California State University.</p></div>"""


def test_sanitize_clears_embedded_state_widget_selections_and_known_values():
    clean = capture_form.sanitize(WIDGETS)
    for gone in ("Jane Roe", "12 Elm Rd", "Elm Rd volunteer", "Lisbon", 'aria-selected="true"',
                 "Sacramento", "California State University"):
        assert gone not in clean, gone
    assert 'data-qa="name-field"' in clean  # a short hook is kept
    assert "Option A" in clean and "Option B" in clean  # option text is not an answer
    assert capture_form.leaks(clean) == []


def test_leaks_reports_a_known_value_and_promises_nothing_more():
    assert capture_form.leaks("<p>Sacramento</p>", ["Sacramento"]) == ["known value"]
    assert capture_form.leaks("<p>Jane Roe, 12 Elm Rd</p>", []) == []  # plain text: read it


#: Fixtures built from fill-probe captures (older fixtures predate the sanitizer).
_PROBE_FIXTURES = ("avature_login", "breezy_social_apply", "eightfold_code_text",
                   "generic_code_boxes", "jobvite_send_application", "label_sources")


def test_fixtures_from_probe_captures_pass_the_leak_check():
    forms = ROOT / "tests/fixtures/forms"
    found = {name: capture_form.leaks((forms / f"{name}.html").read_text(encoding="utf-8"))
             for name in _PROBE_FIXTURES}
    assert not {name: left for name, left in found.items() if left}


class _Context:
    def __init__(self):
        self.socket_handler = None

    def add_init_script(self, script):
        pass

    def route(self, pattern, handler):
        pass

    def route_web_socket(self, pattern, handler):
        self.socket_handler = handler


class _Socket:
    url = "wss://chat.example.com/?session=secret"

    def connect_to_server(self):
        raise AssertionError("a probe socket never reaches the site")

    def close(self, *args):
        raise AssertionError("close() inside the sync handler deadlocks Playwright")


def test_a_page_socket_is_recorded_and_left_unconnected(tmp_path):
    context, audit = _Context(), fill_probe_guard.Audit(tmp_path / "r.jsonl")
    fill_probe_guard.install(context, audit, MARKERS, ANSWERS)
    context.socket_handler(_Socket())
    audit.close()
    assert audit.summary()["counts"] == {"block: websocket": 1}
