"""The Workday credential vault under parallel fills."""

from __future__ import annotations

import threading

from resume_tailor import config
from resume_tailor.apply.answers.profile import ApplicantProfile
from resume_tailor.apply.ats import workday_auth
from resume_tailor.infra import atomic

_URL = "https://aptiv.wd5.myworkdayjobs.com/en-US/aptiv_careers/job/A_J1"


def test_parallel_fills_on_a_new_site_share_one_password(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "APPLICATIONS_OUTPUT_DIR", tmp_path)
    profile = ApplicantProfile(email="applicant@example.com")
    start = threading.Barrier(6, timeout=5)
    seen: list[str] = []

    def fill() -> None:
        start.wait()
        seen.append(workday_auth.get_tenant_credentials(_URL, profile)[1])

    threads = [threading.Thread(target=fill) for _ in range(6)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert len(set(seen)) == 1
    stored = workday_auth._load_vault()["aptiv.wd5.myworkdayjobs.com"]
    assert stored["password"] == seen[0]


def test_flags_written_concurrently_are_all_kept(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "APPLICATIONS_OUTPUT_DIR", tmp_path)
    tenants = [f"site{i}.wd5.myworkdayjobs.com" for i in range(8)]
    threads = [threading.Thread(target=workday_auth._mark_created, args=(t,)) for t in tenants]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    vault = workday_auth._load_vault()
    assert all(vault[tenant]["created"] for tenant in tenants)
    assert not list(tmp_path.glob("*.tmp"))


def test_a_stale_fixed_temp_file_does_not_block_saving(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "APPLICATIONS_OUTPUT_DIR", tmp_path)
    # The old writer's fixed name; a leftover (or a file another writer holds) is ignored.
    (tmp_path / "workday_vault.tmp").write_text("{", encoding="utf-8")
    workday_auth._mark_signed_in("acme.wd5.myworkdayjobs.com")
    assert workday_auth._load_vault()["acme.wd5.myworkdayjobs.com"]["signed_in"] is True


def test_atomic_write_retries_a_briefly_locked_destination(tmp_path, monkeypatch):
    target = tmp_path / "data.json"
    real = atomic.os.replace
    calls = {"n": 0}

    def flaky(src, dst):
        calls["n"] += 1
        if calls["n"] < 3:
            raise PermissionError("in use")
        real(src, dst)

    monkeypatch.setattr(atomic.os, "replace", flaky)
    monkeypatch.setattr(atomic.time, "sleep", lambda _s: None)
    atomic.write_text(target, "{}\n")
    assert target.read_text(encoding="utf-8") == "{}\n"
    assert calls["n"] == 3
    assert not list(tmp_path.glob("*.tmp"))
