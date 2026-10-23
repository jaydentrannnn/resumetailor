"""Pay for an application and imported pay data over HTTP (`routes/pay.py`)."""

from __future__ import annotations

import json

from resume_tailor.apply.funnel import store as apply_store
from resume_tailor.apply.funnel import store_models


def _row(key, company, role, jd, tmp_path, location="Austin, TX", salary=""):
    path = tmp_path / f"{key}.txt"
    path.write_text(jd, encoding="utf-8")
    return store_models.Application(
        source="t", source_job_id=key, company=company, role=role, location=location,
        status="ready", jd_text_path=str(path), salary=salary,
        discovered_at="2026-09-20T00:00:00+00:00",
    )


def test_an_application_shows_its_posted_range_and_similar_roles(client, tmp_path):
    c, _q = client
    apply_store.save_all({
        "me": _row("me", "Acme", "Data Analyst Intern", "Pay: $25/hr - $30/hr", tmp_path),
        "b": _row("b", "Globex", "Data Analytics Intern", "Hourly rate: $22 - $26",
                  tmp_path, location="Dallas, TX"),
        "c": _row("c", "Hooli", "Data Science Intern", "", tmp_path, location="Remote",
                  salary="$40/hr"),
        "d": _row("d", "Initech", "Software Engineer", "$120,000 - $150,000 a year", tmp_path),
    })
    view = c.get("/api/applications/me/pay").json()
    assert [(r["low"], r["high"], r["period"]) for r in view["posted"]] == [(25, 30, "hour")]
    assert view["posted"][0]["excerpt"] == "Pay: $25/hr - $30/hr"
    assert (view["level"], view["family"]) == ("Intern or co-op", "Data and machine learning")
    groups = {g["kind"]: g for g in view["groups"]}
    assert set(groups) == {"near", "anywhere"}
    assert groups["near"]["n"] == 1 and groups["anywhere"]["n"] == 2
    listed = groups["anywhere"]["splits"][0]["figures"]
    assert sorted(f["company"] for f in listed) == ["Globex", "Hooli"]
    assert c.get("/api/applications/nope/pay").status_code == 404


def test_pay_data_is_previewed_imported_listed_and_deleted(client, tmp_path):
    c, _q = client
    csv = (b"Title,Currency,Period,Low,High,Location\n"
           b"Data Analyst Intern,USD,hour,20,28,\"Austin, TX\"\nBad row,,hour,1,2,\n")
    files = {"file": ("survey.csv", csv, "text/csv")}
    preview = c.post("/api/pay/datasets/preview", files=files).json()
    assert preview["mapping"]["role"] == "Title" and preview["total_rows"] == 2
    assert c.get("/api/pay/datasets").json() == []

    saved = c.post("/api/pay/datasets", files=files, data={
        "mapping": json.dumps(preview["mapping"]), "source": "Career centre survey",
        "as_of": "2026-09-01",
    })
    assert saved.status_code == 200
    summary = saved.json()
    assert (summary["row_count"], summary["rejected_count"]) == (1, 1)
    assert summary["source"] == "Career centre survey"

    apply_store.save_all({"me": _row("me", "Acme", "Data Analyst Intern", "", tmp_path)})
    groups = {g["kind"]: g for g in c.get("/api/applications/me/pay").json()["groups"]}
    assert groups["near"]["sources"] == ["survey"]
    assert groups["near"]["first_on"] == "2026-09-01"

    assert c.delete(f"/api/pay/datasets/{summary['id']}").status_code == 204
    assert c.get("/api/pay/datasets").json() == []
    assert c.delete(f"/api/pay/datasets/{summary['id']}").status_code == 404
    bad = c.post("/api/pay/datasets/preview", files={"file": ("x.pdf", b"%PDF", "application/pdf")})
    assert bad.status_code == 422
