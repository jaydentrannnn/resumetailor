"""A posting first seen behind an unresolved link keeps one row once the link resolves.

Regression: a zapply.jobs row saved as ``needs_browser`` (keyed by the wrapper host)
was Prepared after the link started resolving to the real ATS. The new canonical key
missed the index, the same company+role hit the group index, and `_join_group` made a
second row with the same ``source_job_id``. The original stayed ``discovered`` forever,
and the Apply page (which keys rows by ``source_job_id``) lost the ready one.
"""

from __future__ import annotations

from resume_tailor.apply.discovery import identity
from resume_tailor.apply.funnel import daily, store, store_migrations, store_models
from resume_tailor.web.schemas import ApplySettings
from tests.apply.funnel.test_apply_daily import apply_paths, stub_pipeline  # noqa: F401

WRAPPER = "https://zapply.jobs/l/d/oracle-gm-financial-260795"
ORACLE = (
    "https://fa-exvu-saasfaprod1.fa.ocs.oraclecloud.com/hcmUI/CandidateExperience"
    "/en/sites/CX_1/job/260795"
)
SOURCE = "zapply-internships-tech"
SOURCE_JOB_ID = "95127e2acbdb18dd"
COMPANY = "GM Financial"
ROLE = "Intern - Software Development Engineer"


def _wrapper_row(status: str = "needs_browser") -> store_models.Application:
    return store_models.Application(
        source=SOURCE,
        source_job_id=SOURCE_JOB_ID,
        company=COMPANY,
        role=ROLE,
        posting_url=WRAPPER,
        final_url=WRAPPER,
        canonical_key=identity.canonical_key(WRAPPER),
        group_key=identity.group_key(COMPANY, ROLE),
        status=status,
        source_refs=[
            store_models.SourceRef(source=SOURCE, source_job_id=SOURCE_JOB_ID, url=WRAPPER)
        ],
    )


def test_prepare_rekeys_the_row_when_its_link_now_resolves(
    stub_pipeline, apply_paths, monkeypatch  # noqa: F811
):
    assert identity.canonical_key(WRAPPER).startswith("other:")
    store.upsert(_wrapper_row())
    monkeypatch.setattr(identity, "resolve_final_url", lambda url, **k: ORACLE)

    prepared = daily.prepare_application(SOURCE_JOB_ID, settings=ApplySettings(enabled=True))

    rows = store.load_all()
    assert len(rows) == 1, sorted(rows)
    assert prepared.status == "ready"
    assert prepared.canonical_key == identity.canonical_key(ORACLE)
    assert prepared.duplicate_of is None
    assert list(rows) == [identity.canonical_key(ORACLE)]


def test_a_real_ats_key_is_kept_when_the_link_resolves_elsewhere(
    stub_pipeline, apply_paths, monkeypatch  # noqa: F811
):
    """Only a placeholder key (wrapper host, pending) is upgraded; a real one stays."""
    row = _wrapper_row(status="discovered")
    row.canonical_key = identity.canonical_key(ORACLE)
    row.final_url = ORACLE
    store.upsert(row)
    monkeypatch.setattr(identity, "resolve_final_url", lambda url, **k: "https://example.com/x")

    prepared = daily.prepare_application(SOURCE_JOB_ID, settings=ApplySettings(enabled=True))

    assert list(store.load_all()) == [identity.canonical_key(ORACLE)]
    assert prepared.status == "ready"


def test_migration_folds_a_stranded_wrapper_row_into_its_sibling():
    stranded = _wrapper_row(status="discovered")
    real = _wrapper_row(status="ready")
    real.canonical_key = identity.canonical_key(ORACLE)
    real.final_url = ORACLE
    real.duplicate_of = stranded.canonical_key
    real.job_id = "tailor-job-1"
    apps = {stranded.canonical_key: stranded, real.canonical_key: real}

    out, changed = store_migrations._fold_stranded_duplicates(apps)

    assert changed
    assert list(out) == [real.canonical_key]
    kept = out[real.canonical_key]
    assert kept.duplicate_of is None
    assert kept.status == "ready"


def test_prepare_folds_the_row_into_another_sources_requisition(
    stub_pipeline, apply_paths, monkeypatch  # noqa: F811
):
    """The link resolves to a requisition another source already found: one row, that one."""
    other = store_models.Application(
        source="speedyapply",
        source_job_id="speedy-1",
        company=COMPANY,
        role=ROLE,
        posting_url=ORACLE,
        final_url=ORACLE,
        canonical_key=identity.canonical_key(ORACLE),
        group_key=identity.group_key(COMPANY, ROLE),
        job_id="tailor-job-0",
        status="ready",
        source_refs=[
            store_models.SourceRef(source="speedyapply", source_job_id="speedy-1", url=ORACLE)
        ],
    )
    store.upsert(other)
    store.upsert(_wrapper_row())
    monkeypatch.setattr(identity, "resolve_final_url", lambda url, **k: ORACLE)

    prepared = daily.prepare_application(SOURCE_JOB_ID, settings=ApplySettings(enabled=True))

    assert list(store.load_all()) == [identity.canonical_key(ORACLE)]
    assert prepared.source_job_id == "speedy-1"
    assert (SOURCE, SOURCE_JOB_ID) in {(r.source, r.source_job_id) for r in prepared.source_refs}


def test_store_folds_stranded_rows_on_open(apply_paths, monkeypatch):  # noqa: F811
    stranded = _wrapper_row(status="discovered")
    real = _wrapper_row(status="ready")
    real.canonical_key = identity.canonical_key(ORACLE)
    real.duplicate_of = stranded.canonical_key
    real.job_id = "tailor-job-1"
    store.save_all({stranded.canonical_key: stranded, real.canonical_key: real})
    # As a database an older version wrote, opened by a new process.
    monkeypatch.setattr(store, "_repaired", set())
    monkeypatch.setattr(store, "_cache", None)

    assert list(store.load_all()) == [real.canonical_key]
    kept = store.get(SOURCE_JOB_ID)
    assert kept is not None and kept.status == "ready" and kept.duplicate_of is None


def test_fold_rewrites_only_the_rows_it_changes():
    stranded = _wrapper_row(status="discovered")
    stranded.source_refs.append(store_models.SourceRef(source="simplify", source_job_id="extra"))
    real = _wrapper_row(status="ready")
    real.canonical_key = identity.canonical_key(ORACLE)
    real.source_refs = []  # only its primary posting: "extra" has to move across
    bystander = _wrapper_row(status="ready")
    bystander.source_job_id = "unrelated"
    bystander.source_refs = []
    bystander.canonical_key = "greenhouse:acme:1"
    apps = {
        stranded.canonical_key: stranded,
        real.canonical_key: real,
        bystander.canonical_key: bystander,
    }

    out, changed = store_migrations._fold_stranded_duplicates(apps)

    assert changed
    assert out[bystander.canonical_key] is bystander
    assert out[real.canonical_key] is not real and real.source_refs == []
    assert [r.source_job_id for r in out[real.canonical_key].source_refs] == ["extra"]


def test_migration_leaves_a_stranded_row_with_progress_alone():
    """Only an untouched ``discovered`` copy is folded; anything further is kept."""
    stranded = _wrapper_row(status="jd_fetched")
    real = _wrapper_row(status="ready")
    real.canonical_key = identity.canonical_key(ORACLE)
    real.duplicate_of = stranded.canonical_key
    apps = {stranded.canonical_key: stranded, real.canonical_key: real}

    out, changed = store_migrations._fold_stranded_duplicates(apps)

    assert not changed
    assert len(out) == 2


def test_migration_keeps_group_duplicates_of_other_postings():
    """A same-role sibling (different source posting) is a real duplicate: untouched."""
    primary = _wrapper_row(status="discovered")
    sibling = _wrapper_row(status="ready")
    sibling.source_job_id = "another-posting"
    sibling.source_refs = [
        store_models.SourceRef(source=SOURCE, source_job_id="another-posting", url=ORACLE)
    ]
    sibling.canonical_key = identity.canonical_key(ORACLE)
    sibling.duplicate_of = primary.canonical_key
    apps = {primary.canonical_key: primary, sibling.canonical_key: sibling}

    out, changed = store_migrations._fold_stranded_duplicates(apps)

    assert not changed
    assert len(out) == 2
