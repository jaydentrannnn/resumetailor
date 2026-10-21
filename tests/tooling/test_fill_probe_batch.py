"""The large-batch fill probe's offline pieces: the test-account guard rules, field
grading and fill-end categories (`fill_probe_observe`), the target builder
(`fill_probe_targets`), the test inbox parser (`fill_probe_inbox`) and the per-platform
breakdown (`fill_probe.breakdown`). No browser, network or inbox."""

from __future__ import annotations

import json
import sqlite3
import sys
from email.message import EmailMessage
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from evals import (  # noqa: E402
    fill_probe,
    fill_probe_guard,
    fill_probe_inbox,
    fill_probe_observe,
    fill_probe_targets,
)

MARKERS = (b"Zyxt", b"Quorv")
JSON = {"content-type": "application/json"}
TENANT = ("acme.wd5.myworkdayjobs.com",)
LEVER = "https://jobs.lever.co/acme/1b2c3d4e-0000-4000-8000-000000000001"


def _decide(method, url, body=b"", hosts=(), headers=None):
    return fill_probe_guard.decide(
        method, url, headers if headers is not None else JSON, body, MARKERS, (), hosts
    )


# -- guard ---------------------------------------------------------------------------------


def test_an_account_target_writes_its_own_ats_host_only():
    save = _decide("POST", "https://acme.wd5.myworkdayjobs.com/wday/cxs/acme/apply/step",
                   b'{"firstName": "Zyxta"}', TENANT)
    assert (save.allow, save.reason) == (True, "account host")
    upload = _decide("POST", "https://acme.wd5.myworkdayjobs.com/upload", b"%PDF-1.4",
                     TENANT, {"content-type": "application/pdf"})
    assert upload.allow
    elsewhere = _decide("POST", "https://collector.example.net/v1", b'{"n": "Zyxta"}', TENANT)
    assert not elsewhere.allow and elsewhere.marked
    # A look-alike host is not the tenant.
    assert not _decide("POST", "https://acme.wd5.myworkdayjobs.com.evil.net/x",
                       b'{"n": "Zyxta"}', TENANT).allow


def test_a_submit_shaped_request_is_refused_in_every_mode_and_on_every_host():
    for hosts in ((), TENANT):
        for url, body in (
            ("https://acme.wd5.myworkdayjobs.com/wday/cxs/acme/submitApplication", b"{}"),
            ("https://acme.wd5.myworkdayjobs.com/graphql", b'{"query": "mutation SubmitApp { x }"}'),
            ("https://acme.wd5.myworkdayjobs.com/api", b'{"operationName": "finalizeApplication"}'),
        ):
            decision = _decide("POST", url, body, hosts)
            assert (decision.allow, decision.reason) == (False, "submit"), (url, hosts)
    # A read of a page whose path says submit is not a submit.
    assert _decide("GET", "https://jobs.example.com/how-to-submit").allow


def test_named_page_loads_pass_unless_they_carry_the_applicant():
    load = _decide("POST", "https://www.metacareers.com/ajax/bulk-route-definitions/",
                   b"route_urls[0]=/jobs", headers={"content-type": "application/x-www-form-urlencoded"})
    assert (load.allow, load.reason) == (True, "page load")
    marked = _decide("POST", "https://www.metacareers.com/cms/load/", b'{"n": "Zyxta"}')
    assert not marked.allow
    assert not _decide("POST", "https://www.metacareers.com/ajax/other/", b"{}").allow


def test_session_recorders_stay_blocked_on_account_targets():
    assert not _decide("POST", "https://rs.fullstory.com/rec", b"{}", TENANT).allow


def test_the_audit_counts_account_host_data_and_submit_refusals_apart(tmp_path):
    audit = fill_probe_guard.Audit(tmp_path / "r.jsonl")
    audit.record("POST", "https://acme.wd5.myworkdayjobs.com/s", 9,
                 fill_probe_guard.Decision(True, "account host"), identity=True)
    audit.record("POST", "https://acme.wd5.myworkdayjobs.com/submit", 2,
                 fill_probe_guard.Decision(False, "submit"))
    audit.close()
    summary = audit.summary()
    assert summary["allowed_with_applicant_data"] == 0
    assert summary["account_host_with_data"] == 1
    assert summary["submit_refused"] == 1


# -- grading -------------------------------------------------------------------------------


def _snap(*rows):
    return [{"n": 1, "frames": [{"frame": 0, "rows": list(rows)}]}]


def _row(label, shown, **extra):
    return {"label": label, "kind": "text", "required": False, "shown": shown,
            "invalid": False, "message": "", **extra}


def _outcome(label, value, state="verified_filled", key="", required=False):
    return {"label": label, "observed_value": value, "state": state,
            "canonical_key": key, "required": required}


def test_grade_checks_each_answer_against_the_page_and_the_profile():
    profile = SimpleNamespace(phone="(916) 555-0147", city="Sacramento")
    outcomes = [
        _outcome("Phone*", "916-555-0147", key="phone"),
        _outcome("City", "Fresno", key="city"),
        _outcome("Start date", "06/15/2027"),
        _outcome("GPA", "3.7"),
        _outcome("Postal code", "95814"),
        _outcome("Missing label", "x"),
        _outcome("Sponsorship", "", state="unanswered", required=True),
        _outcome("Nickname", "", state="unanswered"),
    ]
    snaps = _snap(
        _row("Phone (required)", "916.555.0147"),
        _row("City", "Fresno"),
        _row("Start date", "2027-06-15"),
        _row("GPA", "7.3"),
        _row("Postal code", "", invalid=True),
        _row("Pronouns", "", required=True),
    )
    graded = fill_probe_observe.grade(outcomes, snaps, profile)
    by_label = {f["label"]: f["grade"] for f in graded["fields"]}
    assert by_label == {
        "Phone*": "ok",
        "City": "wrong_value",
        "Start date": "ok",
        "GPA": "changed",
        "Postal code": "rejected",
        "Missing label": "not_seen",
        "Sponsorship": "blank_required",
        "Nickname": "unanswered_optional",
    }
    assert [f["label"] for f in graded["unrecorded_blank_required"]] == ["Pronouns"]


def test_composite_and_yes_no_answers_are_not_wrong_and_long_labels_are_counted_once():
    profile = SimpleNamespace(city="Sacramento", authorized_to_work=True)
    long = "Please tell us about a research project that you have worked on and what you learned"
    outcomes = [
        _outcome("Location (City)*", "Sacramento, California, United States", key="city"),
        _outcome("Are you legally eligible to work in the U.S.?*", "Yes", key="authorized_to_work"),
    ]
    snaps = _snap(
        _row("Location (City)*", "Sacramento, California, United States"),
        _row("Are you legally eligible to work in the U.S.?*", "Yes"),
        _row(long + "?*", "", required=True),
    )
    graded = fill_probe_observe.grade(
        outcomes, snaps, profile,
        leftovers=[{"label": long[:70], "reason": "needs_review"}], required_empty=[long],
    )
    assert [f["grade"] for f in graded["fields"]] == ["ok", "ok", "blank_required"]
    assert graded["unrecorded_blank_required"] == []


def test_a_question_the_resolver_also_gave_up_on_is_graded_once():
    leftovers = [
        {"label": "Degree*", "reason": "Custom dropdown needs an observed selection"},
        {"label": "Degree*", "reason": "needs_review"},
        {"label": "", "reason": "Unrecognized field"},
        {"label": "", "reason": "Unrecognized field"},
    ]
    graded = fill_probe_observe.grade([], [], leftovers=leftovers, required_empty=["Degree*"])
    assert [(f["label"], f["source"], f["grade"]) for f in graded["fields"]] == [
        ("Degree*", "Custom dropdown needs an observed selection", "blank_required"),
        ("", "Unrecognized field", "unanswered_optional"),
        ("", "Unrecognized field", "unanswered_optional"),
    ]


def test_a_later_snapshot_of_the_same_label_wins():
    snaps = [
        {"n": 1, "frames": [{"frame": 0, "rows": [_row("Email", "")]}]},
        {"n": 2, "frames": [{"frame": 0, "rows": [_row("Email", "a@b.example")]}]},
    ]
    graded = fill_probe_observe.grade([_outcome("Email", "a@b.example")], snaps)
    assert graded["fields"][0]["grade"] == "ok"


def test_fill_end_names_why_the_fill_stopped():
    end = fill_probe_observe.fill_end
    assert end({}, timed_out=True) == "timeout"
    assert end({"status": "x"}, error="Traceback") == "crash"
    assert end({"status": "awaiting_otp"}) == "otp_unresolved"
    assert end({"handoff": "This job is no longer accepting applications"}) == "closed"
    assert end({"handoff": "iCIMS asked for a login. Sign in in the opened tab"}) == "sign_in"
    assert end({"handoff": "Complete the CAPTCHA"}) == "bot_check"
    assert end({"final_step_reached": True}) == "reached_review"
    assert end({"steps_reached": 0, "committed": 0, "status": "awaiting_review"}) == "no_form"
    assert end({"steps_reached": 2, "committed": 5, "status": "awaiting_review"}) == "stopped_mid"


# -- targets -------------------------------------------------------------------------------


def _db(tmp_path, docs):
    path = tmp_path / "app.db"
    connection = sqlite3.connect(path)
    connection.execute("create table applications (key text, doc text)")
    connection.executemany(
        "insert into applications values (?, ?)", [(str(i), json.dumps(d)) for i, d in enumerate(docs)]
    )
    connection.commit()
    connection.close()
    return path


def test_targets_keep_one_posting_per_site_and_drop_capture_only_and_archived(tmp_path):
    wd = "https://acme.wd5.myworkdayjobs.com/en-US/Careers/job/Intern_R{}"
    docs = [
        {"posting_url": wd.format(1), "ats": "workday", "status": "ready", "discovered_at": "2026-10-02"},
        {"posting_url": wd.format(2), "ats": "workday", "status": "submitted", "discovered_at": "2026-10-03"},
        {"posting_url": "https://beta.wd1.myworkdayjobs.com/x/job/R9", "ats": "workday",
         "status": "submitted", "discovered_at": "2026-10-01"},
        {"posting_url": "https://www.linkedin.com/jobs/view/1", "ats": "other", "status": "ready"},
        {"posting_url": "https://www.indeed.com/viewjob?jk=1", "ats": "other", "status": "ready"},
        {"posting_url": "https://job-boards.greenhouse.io/acme/jobs/1", "ats": "greenhouse",
         "status": "ready", "archived_at": "2026-10-04"},
        {"posting_url": LEVER, "ats": "lever", "status": "ready"},
    ]
    path = _db(tmp_path, docs)
    before = path.read_bytes()
    targets = fill_probe_targets.pick(fill_probe_targets.load_rows(path))
    assert path.read_bytes() == before  # read-only
    urls = [t["url"] for t in targets]
    # One per Workday tenant: the newest acme posting, and beta.
    assert urls.count(wd.format(2)) == 1 and wd.format(1) not in urls
    assert "https://beta.wd1.myworkdayjobs.com/x/job/R9" in urls
    assert not any("linkedin" in u or "indeed" in u or "greenhouse" in u for u in urls)
    accounts = {t["url"]: t["account"] for t in targets}
    assert accounts[wd.format(2)] == "account" and accounts[LEVER] == ""
    assert {t["tag"] for t in targets} >= {"workday01", "workday02", "lever01"}


def test_quotas_cap_each_platform_and_alternate_submitted_rows():
    rows = [
        {"url": f"https://jobs.lever.co/co{i}/1b2c3d4e-0000-4000-8000-00000000000{i}", "ats": "lever",
         "status": "submitted" if i % 2 else "ready", "archived": False, "discovered": f"2026-10-{i + 10}"}
        for i in range(6)
    ]
    picked = fill_probe_targets.pick(rows, {"lever": 3})
    assert len(picked) == 3
    statuses = [next(r["status"] for r in rows if r["url"] == t["url"]) for t in picked]
    assert statuses == ["ready", "submitted", "ready"]


def test_the_target_file_round_trips_with_its_account_column(tmp_path):
    targets = [{"tag": "workday01", "url": "https://a.wd1.myworkdayjobs.com/j", "ats": "workday",
                "modes": "live", "account": "account"}]
    path = tmp_path / "t.tsv"
    path.write_text(fill_probe_targets.to_tsv(targets), encoding="utf-8")
    read = fill_probe.read_targets(path, set())
    assert read == targets
    assert fill_probe.live_skip(read[0]) == ""
    assert fill_probe.live_skip({**read[0], "account": ""}) == "needs a test account"


def test_an_icims_account_may_also_write_icims_login_hosts():
    assert fill_probe.ats_hosts("https://careers-acme.icims.com/jobs/1/job", "icims") == [
        "careers-acme.icims.com", "icims.com",
    ]
    assert fill_probe.ats_hosts("https://acme.wd5.myworkdayjobs.com/j", "workday") == [
        "acme.wd5.myworkdayjobs.com",
    ]


# -- inbox ---------------------------------------------------------------------------------


def _mail(subject, text="", html=""):
    message = EmailMessage()
    message["Subject"] = subject
    message["To"] = "probe+rtabc123@gmail.com"
    message.set_content(text or "see html")
    if html:
        message.add_alternative(html, subtype="html")
    return message


def test_the_inbox_reads_a_code_or_a_verification_link():
    code = fill_probe_inbox.extract(_mail("Your code", "Your verification code is: 482913. It expires."))
    assert code.code == "482913"
    reverse = fill_probe_inbox.extract(_mail("Sign in", "A7K29Q is your one-time code"))
    assert reverse.code == "A7K29Q"
    link = fill_probe_inbox.extract(_mail(
        "Verify your account",
        html='<a href="https://acme.example/unsubscribe">x</a>'
             '<a href="https://acme.wd5.myworkdayjobs.com/verify?token=abc&amp;t=1">Verify</a>',
    ))
    assert (link.code, link.link) == ("", "https://acme.wd5.myworkdayjobs.com/verify?token=abc&t=1")
    assert fill_probe_inbox.extract(_mail("Welcome", "Thanks for joining in 2026.")).code == ""


def test_the_alias_is_stable_per_site():
    one = fill_probe_inbox.alias("probe@gmail.com", "workday:acme")
    assert one == fill_probe_inbox.alias("probe@gmail.com", "WORKDAY:acme")
    assert one != fill_probe_inbox.alias("probe@gmail.com", "workday:beta")
    assert one.startswith("probe+rt") and one.endswith("@gmail.com")


# -- breakdown -----------------------------------------------------------------------------


def test_breakdown_counts_ends_grades_and_buckets_per_platform():
    reports = [
        {"ats": "workday", "fill_end": "reached_review",
         "grades": {"fields": [{"grade": "ok"}, {"grade": "changed", "kind": "dropdown"}],
                    "unrecorded_blank_required": [{"kind": "radio"}]}},
        {"ats": "workday", "fill_end": "sign_in", "grades": {"fields": []}},
        {"ats": "lever", "timed_out": True},
        {"questions": []},  # a read-only report is left out
    ]
    table = fill_probe.breakdown(reports)
    assert table["postings"] == {"workday": 2, "lever": 1}
    assert table["ends"][("workday", "sign_in")] == 1
    assert table["ends"][("lever", "timeout")] == 1
    assert table["buckets"][("workday", "changed", "dropdown")] == 1
    assert table["buckets"][("workday", "blank_required_unrecorded", "radio")] == 1
    assert table["buckets"][("workday", "end:sign_in", "")] == 1
    assert ("workday", "end:reached_review", "") not in table["buckets"]
