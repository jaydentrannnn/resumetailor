"""Company research for an application: facts quoted from pages read about the company.

Started by hand only (never nightly). The model call runs on the Light model. Facts are
shown with their source and date and are never resume support. Research is app-wide,
one file per company (`research/company_store.py`), so applications to the same company
share it.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from resume_tailor import config
from resume_tailor.apply.funnel import store as apply_store
from resume_tailor.apply.funnel import store_models
from resume_tailor.research import company_run, company_store, web_search
from resume_tailor.web import job_routing, template_ops

router = APIRouter()


class ResearchRequest(BaseModel):
    #: The company's own site, when search did not find it or there is no search key.
    site_url: str = Field(default="", max_length=500)
    urls: list[str] = Field(default_factory=list, max_length=5)
    notes: list[str] = Field(default_factory=list, max_length=5)
    #: Read the automatic sources again instead of only adding ``urls`` and ``notes``.
    refresh: bool = False


class ResearchView(BaseModel):
    company: str
    research: company_store.CompanyResearch | None = None
    stale: bool = False
    #: The search service a saved key allows ("brave", "tavily"), or "".
    search: str = ""


def _app(source_job_id: str) -> store_models.Application:
    app = apply_store.get(source_job_id)
    if app is None:
        raise HTTPException(status_code=404, detail="Application not found")
    return app


def _jd_text(app: store_models.Application) -> str:
    path = Path(app.jd_text_path) if app.jd_text_path else (
        config.APPLICATIONS_OUTPUT_DIR / app.source_job_id / "jd.txt"
    )
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _view(company: str, research: company_store.CompanyResearch | None) -> ResearchView:
    return ResearchView(
        company=company, research=research,
        stale=research is not None and company_store.is_stale(research),
        search=web_search.provider() or "",
    )


@router.get("/api/applications/{source_job_id}/company-research", response_model=ResearchView)
def get_research(source_job_id: str) -> ResearchView:
    app = _app(source_job_id)
    return _view(app.company, company_store.load(app.company))


@router.post("/api/applications/{source_job_id}/company-research", response_model=ResearchView)
def research_company(source_job_id: str, body: ResearchRequest) -> ResearchView:
    with template_ops.LOCK:
        context = config.default_context()
        app = _app(source_job_id)
        jd_text = _jd_text(app)
    try:
        with config.use_context(context), job_routing.pinned_role("light"):
            research = company_run.run(
                company=app.company, jd_text=jd_text, canonical_key=app.canonical_key,
                site_url=body.site_url, urls=[u for u in body.urls if u.strip()],
                notes=[n[:8000] for n in body.notes if n.strip()], refresh=body.refresh,
            )
    except company_run.NothingToRead as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return _view(app.company, research)


@router.delete(
    "/api/applications/{source_job_id}/company-research/facts/{fact_id}",
    response_model=ResearchView,
)
def remove_fact(source_job_id: str, fact_id: str) -> ResearchView:
    app = _app(source_job_id)
    research = company_store.remove_fact(app.company, fact_id)
    if research is None:
        raise HTTPException(status_code=404, detail="Fact not found")
    return _view(app.company, research)
