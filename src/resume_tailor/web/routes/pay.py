"""Pay for an application: the range its posting states and ranges for similar roles.

Figures come from the profile's saved postings (`research/pay_index`) and pay data the
student imported (`research/pay_import`, app-wide). Nothing here calls a model, and pay
figures are never resume support. Wording in the UI says "posted ranges", never an
estimate of an offer.
"""

from __future__ import annotations

import json

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from pydantic import BaseModel

from resume_tailor.apply.funnel import store as apply_store
from resume_tailor.research import pay_bench, pay_import, pay_index, pay_level
from resume_tailor.research.pay_parse import PostedRange

router = APIRouter()


class PayView(BaseModel):
    #: What this posting itself states, listing first.
    posted: list[PostedRange]
    family: str
    level: str
    groups: list[pay_bench.Group]


async def _read(file: UploadFile) -> bytes:
    data = await file.read(pay_import.MAX_BYTES + 1)
    if len(data) > pay_import.MAX_BYTES:
        raise HTTPException(status_code=413, detail="The file is over 5 MB.")
    return data


@router.get("/api/applications/{source_job_id}/pay", response_model=PayView)
def application_pay(source_job_id: str) -> PayView:
    app = apply_store.get(source_job_id)
    if app is None:
        raise HTTPException(status_code=404, detail="Application not found")
    rows = list(apply_store.rows_view().values())
    figures = [
        *pay_bench.figures_from_postings(pay_index.postings(rows)),
        *pay_bench.figures_from_datasets(pay_import.load_all()),
    ]
    return PayView(
        posted=list(pay_index.ranges_for(app)),
        family=pay_level.FAMILY_LABELS[pay_level.family(app.role)],
        level=pay_level.LEVEL_LABELS[pay_level.level(app.role)],
        groups=pay_bench.benchmark(
            company=app.company, role=app.role, location=app.location, figures=figures,
            exclude_app_id=app.source_job_id,
        ),
    )


@router.post("/api/pay/datasets/preview", response_model=pay_import.Preview)
async def preview_dataset(file: UploadFile = File(...)) -> pay_import.Preview:
    """The file's columns, the guessed mapping and its first rows; nothing is saved."""
    try:
        return pay_import.preview(file.filename or "", await _read(file))
    except pay_import.PayFileError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/api/pay/datasets", response_model=pay_import.DatasetSummary)
async def import_dataset(
    file: UploadFile = File(...),
    mapping: str = Form(...),
    name: str = Form(""),
    source: str = Form(""),
    as_of: str = Form(""),
) -> pay_import.DatasetSummary:
    """Import the file with the confirmed column mapping."""
    try:
        chosen = json.loads(mapping)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=422, detail="The column mapping is not valid.") from exc
    if not isinstance(chosen, dict):
        raise HTTPException(status_code=422, detail="The column mapping is not valid.")
    fields = {k: str(v) for k, v in chosen.items() if k in pay_import.FIELDS and v}
    try:
        dataset = pay_import.save(file.filename or "", await _read(file), fields,  # type: ignore[arg-type]
                                  name=name, source=source, as_of=as_of)
    except pay_import.PayFileError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return pay_import.DatasetSummary(**dataset.model_dump(exclude={"rows"}))


@router.get("/api/pay/datasets", response_model=list[pay_import.DatasetSummary])
def list_datasets() -> list[pay_import.DatasetSummary]:
    return pay_import.summaries()


@router.delete("/api/pay/datasets/{dataset_id}", status_code=204)
def delete_dataset(dataset_id: str) -> None:
    if not pay_import.delete(dataset_id):
        raise HTTPException(status_code=404, detail="That pay data is gone.")
