"""Hermetic tests for the application store (SQLite, with the legacy JSON import)."""

from __future__ import annotations

import json
import sqlite3
import threading

import pytest

from resume_tailor import config
from resume_tailor.apply.funnel import store, store_models, store_views
from resume_tailor.apply.funnel.screen import ScreenResult


def _sample_app(**overrides) -> store_models.Application:
    """Build a minimal application record for store tests."""
    data = {
        "source": "simplify",
        "source_job_id": "job-1",
        "company": "Acme",
        "role": "Intern",
    }
    data.update(overrides)
    return store_models.Application(**data)


@pytest.fixture
def apps_path(tmp_path, monkeypatch):
    """Redirect ``APPLICATIONS_PATH`` into an isolated temp file."""
    path = tmp_path / "applications.json"
    monkeypatch.setattr(config, "APPLICATIONS_PATH", path)
    return path


def _db_rows(apps_path) -> dict[str, dict]:
    """The stored documents, read straight from the database file."""
    conn = sqlite3.connect(apps_path.parent / "app.db")
    try:
        return {key: json.loads(doc) for key, doc in conn.execute("SELECT key, doc FROM applications")}
    finally:
        conn.close()


def _imported(apps_path) -> bool:
    """The legacy file was imported: renamed aside, with a pre-import backup copy."""
    migrated = apps_path.with_name("applications.json.migrated")
    backups = list(apps_path.parent.glob("backup-pre-sqlite-*/applications.json"))
    return not apps_path.exists() and migrated.is_file() and len(backups) == 1


def test_load_all_missing_file_returns_empty(apps_path):
    assert store.load_all() == {}


def test_save_and_load_round_trip(apps_path):
    app = _sample_app(location="SF")
    store.save_all({"job-1": app})
    loaded = store.load_all()
    assert set(loaded) == {"job-1"}
    assert loaded["job-1"].company == "Acme"
    assert loaded["job-1"].location == "SF"
    assert set(_db_rows(apps_path)) == {"job-1"}
    assert not apps_path.exists()  # nothing is written to the legacy JSON file


def test_archive_round_trip_is_idempotent_and_preserves_workflow(apps_path):
    app = _sample_app(status="submitted", job_id="run-1", canonical_key="key-1")
    store.set_status(app, "submitted", note="verified")
    store.save_all({"key-1": app})
    updated, errors = store.set_archived(["job-1", "missing", "job-1"], True)
    assert updated == ["job-1"]
    assert errors == {"missing": "Application not found"}
    first = store.get("key-1")
    assert first is not None and first.archived_at
    store.set_archived(["key-1"], True)
    assert store.get("job-1").archived_at == first.archived_at
    store.set_archived(["job-1"], False)
    restored = store.get("key-1")
    assert restored.status == "ready"
    assert restored.job_id == "run-1"
    assert restored.status_history[:-1] == first.status_history
    assert restored.status_history[-1].note == "Restored from Done; submitted mark undone"
    assert restored.archived_at is None


def test_status_at_sort_uses_latest_status_change():
    old = _sample_app(source_job_id="old", discovered_at="2026-09-01T00:00:00+00:00")
    fresh = _sample_app(source_job_id="fresh", discovered_at="2026-09-02T00:00:00+00:00")
    old.status_history = [
        store_models.StatusChange(status="awaiting_review", at="2026-09-03T00:00:00+00:00")
    ]
    rows = store_views.list_applications(sort="status_at", applications=[fresh, old])
    assert [row.source_job_id for row in rows] == ["old", "fresh"]
    assert store.status_at(fresh) == fresh.discovered_at
    offset = _sample_app(source_job_id="offset", discovered_at="2026-09-03T01:00:00-07:00")
    assert [
        row.source_job_id
        for row in store_views.list_applications(sort="status_at", applications=[old, offset])
    ] == ["offset", "old"]


@pytest.mark.parametrize("previous,expected", [("filling", "ready"), ("tailoring", "tailor_failed"), ("awaiting_review", "awaiting_review")])
def test_undo_terminal_uses_history_and_maps_transients(previous, expected):
    app = _sample_app(status="submitted", job_id="run-1", status_history=[
        store_models.StatusChange(status=previous, at="2026-09-01T00:00:00+00:00"),
        store_models.StatusChange(status="submitted", at="2026-09-02T00:00:00+00:00"),
    ])
    assert store.undo_terminal(app, "mistake")
    assert app.status == expected
    assert app.status_history[-1].status == expected
    assert app.status_history[-1].note == "mistake"
    assert app.revision == 1


def test_undo_terminal_fallback_and_interview_untouched():
    app = _sample_app(status="skipped")
    assert store.undo_terminal(app, "mistake")
    assert app.status == "jd_fetched"
    app = _sample_app(status="interview")
    assert not store.undo_terminal(app, "mistake")
    assert app.status == "interview" and app.status_history == []


def test_archive_search_sort_and_missing_last(apps_path):
    store.save_all({
        "a": _sample_app(source_job_id="a", company="Alpha", role="Engineer", discovered_at="2026-01-01", location="London"),
        "b": _sample_app(source_job_id="b", company="Beta", role="Engineer", discovered_at="2026-01-02", location="Paris", salary="100"),
        "c": _sample_app(source_job_id="c", company="Gamma", role="Designer", archived_at="2026-02-01", salary="200"),
    })
    assert [
        app.source_job_id
        for app in store_views.list_applications(archive="active", sort="salary", direction="asc")
    ] == ["b", "a"]
    assert [
        app.source_job_id
        for app in store_views.list_applications(
            q="eng", sort="company", direction="desc", limit=1, offset=1
        )
    ] == ["a"]
    assert [app.source_job_id for app in store_views.list_applications(archive="archived")] == ["c"]
    assert "archived_at" in store_views.export_csv()


def test_ties_fall_back_to_newest_then_company_and_status_sorts_in_pipeline_order(apps_path):
    rows = [
        _sample_app(source_job_id="old", company="Zed", ats="workday", discovered_at="2026-01-01", status="ready"),
        _sample_app(source_job_id="new", company="Yak", ats="workday", discovered_at="2026-03-01", status="discovered"),
        _sample_app(source_job_id="mid", company="Ace", ats="workday", discovered_at="2026-02-01", status="awaiting_review"),
        _sample_app(source_job_id="gh", company="Bee", ats="greenhouse", discovered_at="2026-01-15", status="submitted"),
    ]
    apps = {row.source_job_id: row for row in rows}
    by_ats = store_views.list_applications(
        sort="ats", direction="asc", applications=list(apps.values())
    )
    assert [row.source_job_id for row in by_ats] == ["gh", "new", "mid", "old"]
    by_status = store_views.list_applications(
        sort="status", direction="asc", applications=list(apps.values())
    )
    assert [row.status for row in by_status] == ["discovered", "ready", "awaiting_review", "submitted"]


def test_review_group_splits_rows_waiting_on_the_applicant(apps_path):
    rows = [
        _sample_app(source_job_id="r", status="awaiting_review"),
        _sample_app(source_job_id="o", status="awaiting_otp"),
        _sample_app(source_job_id="w", status="ready"),
    ]
    review = store_views.list_applications(group="review", applications=rows)
    working = store_views.list_applications(group="working", applications=rows)
    assert {row.source_job_id for row in review} == {"r", "o"}
    assert [row.source_job_id for row in working] == ["w"]


@pytest.mark.parametrize(
    ("status", "fill", "summary"),
    [
        ("ready", None, None),
        ("awaiting_otp", None, "Verification code"),
        ("awaiting_review", {"handoff_reason": "Workday did not accept the saved email and password on this site."}, "Sign-in needed"),
        (
            "awaiting_review",
            {
                "handoff_reason": "missing answers",
                "leftovers": [
                    {"label": "", "reason": "Unrecognized field", "required": True},
                    {"label": "What are your salary expectations for this role?*", "required": True},
                    {"label": "Education: UC Irvine", "reason": "needs_review"},
                ],
                "required_empty": ["primaryQuestionnaire--98ae4442311e1000caac26c618d00003"],
            },
            "What are your salary expectations for this role? +1",
        ),
        ("awaiting_review", {"field_outcomes": [{"label": "Gender", "state": "ambiguous"}]}, "Gender"),
        ("awaiting_review", {"ready_to_submit": True}, "Ready to submit"),
        ("fill_failed", {"error": "boom"}, "Fill failed"),
    ],
)
def test_review_summary(status, fill, summary):
    app = _sample_app(status=status, fill=fill)
    assert store_views.review_summary(app) == summary


@pytest.mark.parametrize("source", ["field_outcomes", "leftovers", "required_empty"])
def test_review_summary_preserves_full_label_and_cleans_whitespace(source):
    label = "  What are your\n salary expectations\tfor this role, including bonus? *  "
    outcome = {"label": label, "state": "manual_review", "required": True}
    fill = {source: [label] if source == "required_empty" else [outcome]}
    app = _sample_app(status="awaiting_review", fill=fill)
    assert store_views.review_summary(app) == (
        "What are your salary expectations for this role, including bonus?"
    )


def test_review_summary_distinguishes_labels_with_the_same_long_prefix():
    prefix = "Please describe your experience working with "
    labels = [prefix + "Python", prefix + "SQL"]
    app = _sample_app(status="awaiting_review", fill={"required_empty": labels + labels})
    assert store_views.review_summary(app) == labels[0] + " +1"


def test_current_registry_imports_once_and_keeps_the_original(apps_path):
    raw = {
        "schema_version": store_models.SCHEMA_VERSION,
        "applications": {
            "a": {"source": "simplify", "source_job_id": "a", "company": "Acme", "role": "Intern"}
        },
    }
    original = json.dumps(raw)
    apps_path.write_text(original, encoding="utf-8")
    assert store.load_all()["a"].archived_at is None
    assert _imported(apps_path)
    assert apps_path.with_name("applications.json.migrated").read_text(encoding="utf-8") == original
    # A file that reappears after the import (a restored copy) is ignored, not re-imported.
    apps_path.write_text(json.dumps({"schema_version": 5, "applications": {}}), encoding="utf-8")
    store._imported.clear()
    assert set(store.load_all()) == {"a"}
    assert apps_path.exists()


def test_corrupt_registry_is_kept_aside_not_fatal(apps_path):
    apps_path.write_text("{not json", encoding="utf-8")
    assert store.load_all() == {}
    assert list(apps_path.parent.glob("applications.json.corrupt-*"))
    assert list(apps_path.parent.glob("backup-pre-sqlite-*/applications.json"))
    store.upsert(_sample_app(source_job_id="new"))
    assert set(store.load_all()) == {"new"}


def test_upsert_and_get(apps_path):
    app = _sample_app(source_job_id="abc")
    store.upsert(app)
    found = store.get("abc")
    assert found is not None
    assert found.role == "Intern"
    app.role = "Updated Intern"
    store.upsert(app)
    assert store.get("abc").role == "Updated Intern"


def test_all_ids(apps_path):
    store.upsert(_sample_app(source="simplify", source_job_id="a"))
    store.upsert(_sample_app(source="simplify", source_job_id="b"))
    assert store.all_ids() == {("simplify", "a"), ("simplify", "b")}


def test_v1_migrates_to_v2(apps_path):
    """A schema-v1 file is rekeyed onto canonical_key and rewritten once."""
    apps_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "applications": {
                    "uuid-1": {
                        "source": "simplify",
                        "source_job_id": "uuid-1",
                        "company": "Figma",
                        "role": "Intern",
                        "posting_url": (
                            "https://boards.greenhouse.io/figma/jobs/6143238004"
                        ),
                        "discovered_at": "2026-01-01T00:00:00+00:00",
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    loaded = store.load_all()
    assert len(loaded) == 1
    app = next(iter(loaded.values()))
    assert app.canonical_key == "greenhouse:figma:6143238004"
    assert app.source_refs[0].source_job_id == "uuid-1"
    assert "greenhouse:figma:6143238004" in _db_rows(apps_path)
    assert _imported(apps_path)
    # get works by legacy source_job_id and by canonical key
    assert store.get("uuid-1") is not None
    assert store.get("greenhouse:figma:6143238004") is not None


def test_build_index_groups_by_group_key(apps_path):
    """Two apps sharing ``group_key`` appear together in ``by_group``."""
    a = _sample_app(
        source_job_id="a",
        canonical_key="greenhouse:x:1",
        group_key="acme|software intern",
        company="Acme",
        role="Software Intern - SF",
    )
    b = _sample_app(
        source_job_id="b",
        canonical_key="greenhouse:x:2",
        group_key="acme|software intern",
        company="Acme",
        role="Software Intern - NYC",
    )
    store.upsert(a)
    store.upsert(b)
    index = store.build_index()
    assert set(index.by_group["acme|software intern"]) == {
        "greenhouse:x:1",
        "greenhouse:x:2",
    }


def test_set_status_appends_history(apps_path):
    app = _sample_app()
    store.set_status(app, "jd_fetched", note="fetched jd")
    assert app.status == "jd_fetched"
    assert len(app.status_history) == 1
    assert app.status_history[0].status == "jd_fetched"
    assert app.status_history[0].note == "fetched jd"
    assert app.status_history[0].at.endswith("+00:00") or "T" in app.status_history[0].at


def test_set_status_blocks_terminal_to_pre_ready():
    app = _sample_app(status="submitted")
    app.status_history = [
        store_models.StatusChange(status="submitted", at="2026-01-01T00:00:00+00:00")
    ]
    with pytest.raises(ValueError, match="terminal"):
        store.set_status(app, "discovered")
    with pytest.raises(ValueError, match="terminal"):
        store.set_status(app, "tailoring")


def test_set_status_allows_terminal_to_post_ready():
    app = _sample_app(status="submitted")
    store.set_status(app, "interview", note="callback")
    assert app.status == "interview"


def test_failed_write_rolls_back_the_whole_transaction(apps_path, monkeypatch):
    """A write that fails part-way leaves every row as it was, and the cache honest."""
    store.save_all({"a": _sample_app(source_job_id="a"), "b": _sample_app(source_job_id="b")})
    real_put = store._put
    calls = {"n": 0}

    def _failing_put(conn, key, app):
        calls["n"] += 1
        if calls["n"] == 2:
            raise sqlite3.OperationalError("disk I/O error")
        real_put(conn, key, app)

    monkeypatch.setattr(store, "_put", _failing_put)
    with pytest.raises(sqlite3.OperationalError):
        store.save_all({"a": _sample_app(source_job_id="a", notes="x"), "c": _sample_app(source_job_id="c")})
    monkeypatch.setattr(store, "_put", real_put)
    assert set(store.load_all()) == {"a", "b"}
    assert store.get("a").notes == ""
    assert set(_db_rows(apps_path)) == {"a", "b"}


def test_concurrent_updates_from_threads_lose_nothing(apps_path):
    store.upsert(_sample_app(canonical_key="k"))

    def _worker(field: str) -> None:
        for i in range(50):
            store.patch("k", **{field: f"{field}-{i}"})

    threads = [threading.Thread(target=_worker, args=(name,)) for name in ("notes", "salary")]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    row = store.get("k")
    assert row.notes == "notes-49" and row.salary == "salary-49"
    assert row.revision == 101


def _v2_registry(applications: dict) -> dict:
    """A schema-v2 registry payload, as ``applications.json`` would hold it."""
    return {"schema_version": 2, "applications": applications}


def test_v2_migrates_workday_keys_to_last_path_segment_id(apps_path):
    """A wrong pre-fix key (first letters-plus-year anywhere in the path) is
    re-keyed onto the id after the URL's final ``_``, and any row pointing at
    it via ``duplicate_of`` follows along."""
    url = (
        "https://amfam.wd1.myworkdayjobs.com/AmFamGroupInternCareers/job/"
        "WI-Madison/Consumer-Research-and-Insights-Intern-2027_R39474"
    )
    apps_path.write_text(
        json.dumps(
            _v2_registry(
                {
                    "workday:amfam:ERN-2027": {
                        "source": "simplify",
                        "source_job_id": "job-1",
                        "company": "AmFam",
                        "role": "Consumer Research Intern",
                        "posting_url": url,
                        "final_url": url,
                        "canonical_key": "workday:amfam:ERN-2027",
                        "ats": "workday",
                        "discovered_at": "2026-01-01T00:00:00+00:00",
                    },
                    "workday:amfam:MER-2027": {
                        "source": "simplify",
                        "source_job_id": "job-2",
                        "company": "AmFam",
                        "role": "Customer Analytics Intern",
                        "posting_url": url,
                        "final_url": url,
                        "canonical_key": "workday:amfam:MER-2027",
                        "duplicate_of": "workday:amfam:ERN-2027",
                        "ats": "workday",
                        "discovered_at": "2026-01-01T00:00:00+00:00",
                    },
                }
            )
        ),
        encoding="utf-8",
    )
    loaded = store.load_all()
    assert "workday:amfam:R39474" in loaded
    assert "workday:amfam:ERN-2027" not in loaded
    renamed = loaded["workday:amfam:R39474"]
    assert renamed.source_job_id == "job-1"
    other = next(a for a in loaded.values() if a.source_job_id == "job-2")
    assert other.duplicate_of == "workday:amfam:R39474"

    assert _imported(apps_path)

    # A second load is a no-op: no further re-keying, no second backup.
    store.load_all()
    assert _imported(apps_path)


def test_v2_migration_keeps_old_key_on_collision(apps_path):
    """If recomputing a key would collide with an existing row, the old (wrong)
    key is kept rather than silently dropping one row."""
    url = (
        "https://amfam.wd1.myworkdayjobs.com/AmFamGroupInternCareers/job/"
        "WI-Madison/Consumer-Research-and-Insights-Intern-2027_R39474"
    )
    apps_path.write_text(
        json.dumps(
            _v2_registry(
                {
                    "workday:amfam:ERN-2027": {
                        "source": "simplify",
                        "source_job_id": "job-1",
                        "company": "AmFam",
                        "role": "Intern A",
                        "posting_url": url,
                        "final_url": url,
                        "canonical_key": "workday:amfam:ERN-2027",
                        "discovered_at": "2026-01-01T00:00:00+00:00",
                    },
                    "workday:amfam:R39474": {
                        "source": "simplify",
                        "source_job_id": "job-2",
                        "company": "AmFam",
                        "role": "Intern B",
                        "posting_url": url,
                        "final_url": url,
                        "canonical_key": "workday:amfam:R39474",
                        "discovered_at": "2026-01-01T00:00:00+00:00",
                    },
                }
            )
        ),
        encoding="utf-8",
    )
    loaded = store.load_all()
    assert len(loaded) == 2
    assert "workday:amfam:ERN-2027" in loaded
    assert "workday:amfam:R39474" in loaded


def test_v2_migration_backfills_unknown_ats(apps_path):
    """A row discovered before its first fetch has ``ats == "unknown"``; the
    migration fills it in from the posting URL."""
    apps_path.write_text(
        json.dumps(
            _v2_registry(
                {
                    "workday:amfam:R39474": {
                        "source": "simplify",
                        "source_job_id": "job-1",
                        "company": "AmFam",
                        "role": "Intern",
                        "posting_url": (
                            "https://amfam.wd1.myworkdayjobs.com/Careers/job/"
                            "WI-Madison/Intern_R39474"
                        ),
                        "canonical_key": "workday:amfam:R39474",
                        "ats": "unknown",
                        "discovered_at": "2026-01-01T00:00:00+00:00",
                    }
                }
            )
        ),
        encoding="utf-8",
    )
    loaded = store.load_all()
    assert loaded["workday:amfam:R39474"].ats == "workday"


def test_v2_migration_is_noop_without_workday_or_unknown_rows(apps_path):
    """A clean v2 registry imports unchanged."""
    apps_path.write_text(
        json.dumps(
            _v2_registry(
                {
                    "greenhouse:figma:1": {
                        "source": "simplify",
                        "source_job_id": "job-1",
                        "company": "Figma",
                        "role": "Intern",
                        "canonical_key": "greenhouse:figma:1",
                        "ats": "greenhouse",
                        "discovered_at": "2026-01-01T00:00:00+00:00",
                    }
                }
            )
        ),
        encoding="utf-8",
    )
    loaded = store.load_all()
    assert set(loaded) == {"greenhouse:figma:1"} and loaded["greenhouse:figma:1"].ats == "greenhouse"
    assert _imported(apps_path)


def test_set_status_submitted_archives_the_row(apps_path):
    app = _sample_app(status="awaiting_review")
    store.set_status(app, "submitted", note="confirmed")
    assert app.archived_at is not None


def test_set_status_skipped_archives_the_row_once(apps_path):
    """Skipping moves a row to the Apply page's Done tab; a restore sticks."""
    app = _sample_app(status="ready")
    store.set_status(app, "skipped")
    assert app.archived_at == app.status_history[-1].at
    app.archived_at = None
    store.set_status(app, "skipped", note="still skipped")
    assert app.archived_at is None


def test_set_status_screened_out_archives_new_and_restored_rows(apps_path):
    app = _sample_app(status="jd_fetched")
    store.set_status(app, "screened_out", note="prefilter: citizenship_required")
    assert app.archived_at == app.status_history[-1].at

    app.archived_at = None  # Applicant restored the row to recheck it.
    store.set_status(app, "screened_out", note="prefilter: citizenship_required")
    assert app.archived_at == app.status_history[-1].at


def test_set_status_submit_unconfirmed_stays_in_working_queue(apps_path):
    app = _sample_app(status="filling")
    store.set_status(app, "submit_unconfirmed")
    assert app.archived_at is None


def test_restored_submitted_row_is_not_rearchived_by_a_note(apps_path):
    app = _sample_app(status="submitted")
    store.set_status(app, "submitted", note="follow-up")
    assert app.archived_at is None


def test_v3_registry_archives_submitted_rows_once(apps_path):
    submitted = {"source": "simplify", "source_job_id": "s", "company": "Acme", "role": "Intern", "status": "submitted",
                 "status_history": [{"status": "submitted", "at": "2026-09-01T12:00:00+00:00", "note": ""}]}
    unconfirmed = {"source": "simplify", "source_job_id": "u", "company": "Beta", "role": "Intern", "status": "submit_unconfirmed"}
    apps_path.write_text(json.dumps({"schema_version": 3, "applications": {"s": submitted, "u": unconfirmed}}), encoding="utf-8")

    loaded = store.load_all()
    assert loaded["s"].archived_at == "2026-09-01T12:00:00+00:00"
    assert loaded["u"].archived_at is None
    assert _imported(apps_path)

    # A later restore sticks: the migration does not run again on an upgraded file.
    store.set_archived(["s"], False)
    assert store.load_all()["s"].archived_at is None


def test_v4_registry_archives_screened_out_rows_once_preserving_details(apps_path):
    history_at = "2026-09-20T12:00:00+00:00"
    rejected = _sample_app(source_job_id="rejected", status="screened_out")
    rejected.status_history = [
        store_models.StatusChange(
            status="screened_out", at=history_at, note="prefilter: citizenship_required"
        )
    ]
    rejected.screen = ScreenResult(passed=False, reasons=["citizenship_required"])
    already_archived = _sample_app(source_job_id="archived", status="screened_out", archived_at="2026-09-19T00:00:00+00:00")
    no_history = _sample_app(source_job_id="no-history", status="screened_out")
    ready = _sample_app(source_job_id="ready", status="ready")
    apps_path.write_text(json.dumps({"schema_version": 4, "applications": {
        "rejected": rejected.model_dump(mode="json"),
        "archived": already_archived.model_dump(mode="json"),
        "no-history": no_history.model_dump(mode="json"),
        "ready": ready.model_dump(mode="json"),
    }}), encoding="utf-8")

    loaded = store.load_all()
    assert loaded["rejected"].archived_at == history_at
    assert loaded["rejected"].screen.reasons == ["citizenship_required"]
    assert loaded["rejected"].status_history == rejected.status_history
    assert loaded["archived"].archived_at == already_archived.archived_at
    assert loaded["no-history"].archived_at is not None
    assert loaded["ready"].archived_at is None
    assert _imported(apps_path)

    store.set_archived(["rejected"], False)
    assert store.load_all()["rejected"].archived_at is None
    assert _imported(apps_path)


# --- concurrent writers (B1/B12) -------------------------------------------------


def test_stale_row_write_keeps_a_concurrent_change(apps_path):
    """A row held across a long operation writes back only what it changed."""
    store.upsert(_sample_app(canonical_key="gh:acme:1"))
    held = store.get("gh:acme:1")  # e.g. fill reads the row, then drives a browser
    user = store.get("gh:acme:1")
    user.notes = "call recruiter"
    store.upsert(user)
    store.set_archived(["gh:acme:1"], True)

    held.error = "fill failed"
    store.upsert(held)

    stored = store.get("gh:acme:1")
    assert stored.notes == "call recruiter"
    assert stored.archived_at
    assert stored.error == "fill failed"
    # The held object is refreshed to the merged row, so its next write is not stale.
    assert held.notes == "call recruiter" and held.archived_at == stored.archived_at


def test_late_fill_does_not_unsubmit_a_row(apps_path):
    store.upsert(_sample_app(canonical_key="gh:acme:1", status="filling"))
    fill_view = store.get("gh:acme:1")
    store.update("gh:acme:1", lambda app: store.set_status(app, "submitted", note="by hand"))

    store.set_status(fill_view, "awaiting_review", note="fill done")
    fill_view.error = None
    fill_view.fill = store_models.FillResult(ready_to_submit=True)
    store.upsert(fill_view)

    stored = store.get("gh:acme:1")
    assert stored.status == "submitted"
    assert stored.archived_at  # submit archives, and the late write did not undo it
    assert stored.fill.ready_to_submit is True  # the fill's own result is still saved
    assert "status kept" in stored.status_history[-1].note
    assert [c.status for c in stored.status_history][-3:] == [
        "submitted",
        "awaiting_review",
        "submitted",
    ]


def test_status_history_entries_from_both_writers_survive(apps_path):
    store.upsert(_sample_app(canonical_key="k"))
    first = store.get("k")
    second = store.get("k")
    store.set_status(first, "jd_fetched", note="a")
    store.upsert(first)
    second.notes = "n"
    store.set_status(second, "screened_in", note="b")
    store.upsert(second)
    notes = [c.note for c in store.get("k").status_history]
    assert notes == ["a", "b"]


def test_parallel_updates_lose_nothing(apps_path):
    import threading

    store.upsert(_sample_app(canonical_key="k"))

    def bump(field_name: str) -> None:
        for i in range(100):
            store.patch("k", **{field_name: f"{field_name}-{i}"})

    threads = [threading.Thread(target=bump, args=(name,)) for name in ("notes", "salary")]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    stored = store.get("k")
    assert stored.notes == "notes-99"
    assert stored.salary == "salary-99"
    assert stored.revision == 201


def test_update_missing_row_raises(apps_path):
    with pytest.raises(store.StaleApplication):
        store.update("nope", lambda app: None)


def test_update_resolves_a_source_job_id(apps_path):
    store.upsert(_sample_app(canonical_key="gh:acme:1", source_job_id="sid-1"))
    store.patch("sid-1", notes="found")
    assert store.get("gh:acme:1").notes == "found"


def test_rekey_through_merge_moves_the_row(apps_path):
    store.upsert(_sample_app(canonical_key="pending:job-1"))
    app = store.get("pending:job-1")
    app.canonical_key = "gh:acme:1"
    store.upsert(app)
    assert set(store.load_all()) == {"gh:acme:1"}


def test_restore_keeps_user_notes_and_terminal_status(apps_path):
    store.upsert(_sample_app(canonical_key="k", status="ready", job_id="j1"))
    previous = store.get("k").model_copy(deep=True)
    store.update("k", lambda app: setattr(app, "job_id", "j2"))
    store.patch("k", notes="mine")
    store.restore(previous)
    stored = store.get("k")
    assert stored.job_id == "j1" and stored.notes == "mine" and stored.status == "ready"

    store.update("k", lambda app: store.set_status(app, "skipped"))
    store.restore(previous)
    assert store.get("k").status == "skipped"


def test_get_rereads_after_another_process_writes(apps_path):
    """A write through a separate connection (the nightly CLI) is seen on the next read."""
    store.upsert(_sample_app(canonical_key="k"))
    assert store.get("k").company == "Acme"
    doc = _db_rows(apps_path)["k"]
    doc["company"] = "Beta"
    conn = sqlite3.connect(apps_path.parent / "app.db")
    with conn:
        conn.execute("UPDATE applications SET doc = ? WHERE key = 'k'", (json.dumps(doc),))
        conn.execute("UPDATE meta SET value = value + 1 WHERE name = 'applications'")
    conn.close()
    assert store.get("k").company == "Beta"


def test_returned_rows_are_private_copies(apps_path):
    store.upsert(_sample_app(canonical_key="k"))
    store.get("k").company = "mutated"
    store.load_all()["k"].notes = "mutated"
    stored = store.get("k")
    assert stored.company == "Acme" and stored.notes == ""


def test_posted_date_prefers_the_stated_date_then_the_age_then_the_date_found():
    stated = _sample_app(posted_at="2026-08-30", discovered_at="2026-09-20T10:00:00+00:00", age_days=3)
    aged = _sample_app(discovered_at="2026-09-20T10:00:00+00:00", age_days=3)
    unknown = _sample_app(discovered_at="2026-09-20T10:00:00+00:00", age_days=0, eligibility_flags=["age_unknown"])
    captured = _sample_app(discovered_at="2026-09-20T10:00:00+00:00")
    assert store_models.posted_date(stated) == ("2026-08-30", True)
    assert store_models.posted_date(aged) == ("2026-09-17", True)
    assert store_models.posted_date(unknown) == ("2026-09-20", False)
    assert store_models.posted_date(captured) == ("2026-09-20", False)
    assert store_models.posted_date(_sample_app()) == ("", False)


def test_sort_by_posted_date_orders_by_publication_not_discovery(apps_path):
    store.save_all({
        # Found last, but posted first: a 30-day-old posting found today.
        "old": _sample_app(source_job_id="old", company="Old", discovered_at="2026-09-20T00:00:00+00:00", age_days=30),
        "new": _sample_app(source_job_id="new", company="New", discovered_at="2026-09-10T00:00:00+00:00", posted_at="2026-09-09"),
        "cap": _sample_app(source_job_id="cap", company="Captured", discovered_at="2026-09-15T00:00:00+00:00"),
    })
    newest_first = [app.source_job_id for app in store_views.list_applications(sort="posted_at")]
    assert newest_first == ["cap", "new", "old"]
    assert [app.source_job_id for app in store_views.list_applications(sort="discovered_at")] == [
        "old",
        "cap",
        "new",
    ]
