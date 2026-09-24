"""Hermetic tests for the applications.json store."""

from __future__ import annotations

import json

import pytest

from resume_tailor import config
from resume_tailor.apply import store
from resume_tailor.apply.screen import ScreenResult


def _sample_app(**overrides) -> store.Application:
    """Build a minimal application record for store tests."""
    data = {
        "source": "simplify",
        "source_job_id": "job-1",
        "company": "Acme",
        "role": "Intern",
    }
    data.update(overrides)
    return store.Application(**data)


@pytest.fixture
def apps_path(tmp_path, monkeypatch):
    """Redirect ``APPLICATIONS_PATH`` into an isolated temp file."""
    path = tmp_path / "applications.json"
    monkeypatch.setattr(config, "APPLICATIONS_PATH", path)
    return path


def test_load_all_missing_file_returns_empty(apps_path):
    assert store.load_all() == {}


def test_save_and_load_round_trip(apps_path):
    app = _sample_app(location="SF")
    store.save_all({"job-1": app})
    loaded = store.load_all()
    assert set(loaded) == {"job-1"}
    assert loaded["job-1"].company == "Acme"
    assert loaded["job-1"].location == "SF"
    raw = json.loads(apps_path.read_text(encoding="utf-8"))
    assert raw["schema_version"] == store.SCHEMA_VERSION
    assert "job-1" in raw["applications"]


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
    assert restored.status == "submitted"
    assert restored.job_id == "run-1"
    assert restored.status_history == first.status_history
    assert restored.archived_at is None


def test_archive_search_sort_and_missing_last(apps_path):
    store.save_all({
        "a": _sample_app(source_job_id="a", company="Alpha", role="Engineer", discovered_at="2026-01-01", location="London"),
        "b": _sample_app(source_job_id="b", company="Beta", role="Engineer", discovered_at="2026-01-02", location="Paris", salary="100"),
        "c": _sample_app(source_job_id="c", company="Gamma", role="Designer", archived_at="2026-02-01", salary="200"),
    })
    assert [app.source_job_id for app in store.list_applications(archive="active", sort="salary", direction="asc")] == ["b", "a"]
    assert [app.source_job_id for app in store.list_applications(q="eng", sort="company", direction="desc", limit=1, offset=1)] == ["a"]
    assert [app.source_job_id for app in store.list_applications(archive="archived")] == ["c"]
    assert "archived_at" in store.export_csv()


def test_ties_fall_back_to_newest_then_company_and_status_sorts_in_pipeline_order(apps_path):
    rows = [
        _sample_app(source_job_id="old", company="Zed", ats="workday", discovered_at="2026-01-01", status="ready"),
        _sample_app(source_job_id="new", company="Yak", ats="workday", discovered_at="2026-03-01", status="discovered"),
        _sample_app(source_job_id="mid", company="Ace", ats="workday", discovered_at="2026-02-01", status="awaiting_review"),
        _sample_app(source_job_id="gh", company="Bee", ats="greenhouse", discovered_at="2026-01-15", status="submitted"),
    ]
    apps = {row.source_job_id: row for row in rows}
    by_ats = store.list_applications(sort="ats", direction="asc", applications=list(apps.values()))
    assert [row.source_job_id for row in by_ats] == ["gh", "new", "mid", "old"]
    by_status = store.list_applications(sort="status", direction="asc", applications=list(apps.values()))
    assert [row.status for row in by_status] == ["discovered", "ready", "awaiting_review", "submitted"]


def test_review_group_splits_rows_waiting_on_the_applicant(apps_path):
    rows = [
        _sample_app(source_job_id="r", status="awaiting_review"),
        _sample_app(source_job_id="o", status="awaiting_otp"),
        _sample_app(source_job_id="w", status="ready"),
    ]
    review = store.list_applications(group="review", applications=rows)
    working = store.list_applications(group="working", applications=rows)
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
            "What are your salary expectations for… +1",
        ),
        ("awaiting_review", {"field_outcomes": [{"label": "Gender", "state": "ambiguous"}]}, "Gender"),
        ("awaiting_review", {"ready_to_submit": True}, "Ready to submit"),
        ("fill_failed", {"error": "boom"}, "Fill failed"),
    ],
)
def test_review_summary(status, fill, summary):
    app = _sample_app(status=status, fill=fill)
    assert store.review_summary(app) == summary


def test_current_registry_load_does_not_rewrite_to_add_archive_field(apps_path):
    raw = {"schema_version": store.SCHEMA_VERSION, "applications": {"a": {"source": "simplify", "source_job_id": "a", "company": "Acme", "role": "Intern"}}}
    original = json.dumps(raw)
    apps_path.write_text(original, encoding="utf-8")
    assert store.load_all()["a"].archived_at is None
    assert apps_path.read_text(encoding="utf-8") == original


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
    raw = json.loads(apps_path.read_text(encoding="utf-8"))
    assert raw["schema_version"] == store.SCHEMA_VERSION
    assert "greenhouse:figma:6143238004" in raw["applications"]
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
        store.StatusChange(status="submitted", at="2026-01-01T00:00:00+00:00")
    ]
    with pytest.raises(ValueError, match="terminal"):
        store.set_status(app, "discovered")
    with pytest.raises(ValueError, match="terminal"):
        store.set_status(app, "tailoring")


def test_set_status_allows_terminal_to_post_ready():
    app = _sample_app(status="submitted")
    store.set_status(app, "interview", note="callback")
    assert app.status == "interview"


def test_atomic_write_uses_tmp_suffix(apps_path, monkeypatch):
    """Persist via ``.json.tmp`` then replace — no partial read of half a file."""
    writes: list[str] = []

    def _tracked_write_text(self, data, encoding="utf-8"):
        writes.append(self.name)
        return Path_write_text(self, data, encoding=encoding)

    Path_write_text = type(apps_path).write_text
    monkeypatch.setattr(type(apps_path), "write_text", _tracked_write_text)
    replaced: list[tuple] = []

    def _tracked_replace(self, target):
        replaced.append((self.name, target.name))
        return Path_replace(self, target)

    Path_replace = type(apps_path).replace
    monkeypatch.setattr(type(apps_path), "replace", _tracked_replace)

    store.save_all({"job-1": _sample_app()})
    assert any(name.endswith(".json.tmp") for name in writes)
    assert replaced
    assert not (apps_path.parent / "applications.json.tmp").exists()


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

    raw = json.loads(apps_path.read_text(encoding="utf-8"))
    assert raw["schema_version"] == store.SCHEMA_VERSION
    backups = list(apps_path.parent.glob("applications.json.bak-*"))
    assert len(backups) == 1

    # A second load is a no-op: no further re-keying, no second backup.
    store.load_all()
    assert len(list(apps_path.parent.glob("applications.json.bak-*"))) == 1


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
    """A clean v2 registry is bumped to the current schema without a backup."""
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
    store.load_all()
    raw = json.loads(apps_path.read_text(encoding="utf-8"))
    assert raw["schema_version"] == store.SCHEMA_VERSION
    assert not list(apps_path.parent.glob("applications.json.bak-*"))


def test_set_status_submitted_archives_the_row(apps_path):
    app = _sample_app(status="awaiting_review")
    store.set_status(app, "submitted", note="confirmed")
    assert app.archived_at is not None


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
    assert json.loads(apps_path.read_text(encoding="utf-8"))["schema_version"] == store.SCHEMA_VERSION
    assert list(apps_path.parent.glob("applications.json.bak-*"))

    # A later restore sticks: the migration does not run again on an upgraded file.
    store.set_archived(["s"], False)
    assert store.load_all()["s"].archived_at is None


def test_v4_registry_archives_screened_out_rows_once_preserving_details(apps_path):
    history_at = "2026-09-20T12:00:00+00:00"
    rejected = _sample_app(source_job_id="rejected", status="screened_out")
    rejected.status_history = [store.StatusChange(status="screened_out", at=history_at, note="prefilter: citizenship_required")]
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
    assert json.loads(apps_path.read_text(encoding="utf-8"))["schema_version"] == store.SCHEMA_VERSION
    assert len(list(apps_path.parent.glob("applications.json.bak-*"))) == 1

    store.set_archived(["rejected"], False)
    assert store.load_all()["rejected"].archived_at is None
    assert len(list(apps_path.parent.glob("applications.json.bak-*"))) == 1
