"""Company research routes (`web/routes/company_research.py`), offline with a fake model."""

from __future__ import annotations

from resume_tailor import config
from resume_tailor.apply.funnel import store, store_models
from resume_tailor.pipeline import company_research
from resume_tailor.pipeline.company_research import FactLLM, FactsLLM
from resume_tailor.research import web_search


class _Reply:
    def __init__(self, parsed):
        self.parsed_output = parsed
        self.stop_reason = "end_turn"


def _seed(tmp_path):
    jd = tmp_path / "jd.txt"
    jd.write_text("About Acme\nAcme builds dashboards for hospitals.\n\nWhat you'll do\nSQL.",
                  "utf-8")
    store.upsert(store_models.Application(
        source="simplify", source_job_id="acme1", company="Acme Analytics",
        role="Data Analyst Intern", jd_text_path=str(jd),
    ))


def _fake_model(monkeypatch, facts):
    class _Client:
        def __init__(self):
            self.messages = self

        def parse(self, **kwargs):
            sid = kwargs["messages"][0]["content"].split('<source id="')[1].split('"')[0]
            return _Reply(FactsLLM(facts=[f.model_copy(update={"source_id": sid}) for f in facts]))

    monkeypatch.setattr(company_research.llm, "client_for", lambda purpose: _Client())
    monkeypatch.setattr(config, "anthropic_api_key", lambda: "test-key")
    monkeypatch.setattr(web_search, "provider", lambda: None)


def test_research_reads_the_posting_and_facts_can_be_removed(client, tmp_path, monkeypatch):
    client, _q = client
    _seed(tmp_path)
    _fake_model(monkeypatch, [
        FactLLM(text="Acme builds dashboards for hospitals.", kind="about",
                excerpt="Acme builds dashboards for hospitals."),
        FactLLM(text="Acme has 900 staff.", kind="size", excerpt="Acme builds dashboards"),
    ])
    empty = client.get("/api/applications/acme1/company-research").json()
    assert empty == {"company": "Acme Analytics", "research": None, "stale": False, "search": ""}

    made = client.post("/api/applications/acme1/company-research", json={}).json()
    research = made["research"]
    assert [f["text"] for f in research["facts"]] == ["Acme builds dashboards for hospitals."]
    assert research["dropped"] == 1 and research["sources"][0]["kind"] == "posting"

    fid = research["facts"][0]["id"]
    after = client.delete(f"/api/applications/acme1/company-research/facts/{fid}").json()
    assert after["research"]["facts"] == [] and after["research"]["removed"] == [fid]
    assert client.delete(f"/api/applications/acme1/company-research/facts/{fid}").status_code == 404


def test_nothing_to_read_and_unknown_applications(client, tmp_path, monkeypatch):
    client, _q = client
    store.upsert(store_models.Application(source="simplify", source_job_id="bare",
                                          company="Bare Co", role="Intern"))
    _fake_model(monkeypatch, [])
    response = client.post("/api/applications/bare/company-research", json={})
    assert response.status_code == 422 and "add a page or a note" in response.json()["detail"]
    noted = client.post("/api/applications/bare/company-research",
                        json={"notes": ["Bare Co makes boxes."]}).json()
    assert [s["kind"] for s in noted["research"]["sources"]] == ["note"]
    assert client.get("/api/applications/nope/company-research").status_code == 404
