"""Job-description input helpers for the Tailor page: fetch from a URL, read a file.

Both return text for the student to review before a run; neither starts one.
"""

from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, File, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from resume_tailor.pipeline import jd_input

router = APIRouter()


class JdFetchRequest(BaseModel):
    url: str = Field(min_length=1, max_length=2000)


def _error(exc: jd_input.JdInputError) -> JSONResponse:
    return JSONResponse(status_code=422, content={"detail": str(exc), "error": exc.code})


@router.post("/api/jd/fetch")
async def fetch_jd_url(body: JdFetchRequest):
    # Network and possibly a browser round-trip: keep it off the event loop.
    try:
        result = await run_in_threadpool(jd_input.from_url, body.url)
    except jd_input.JdInputError as exc:
        return _error(exc)
    return asdict(result)


@router.post("/api/jd/extract-file")
async def extract_jd_file(file: UploadFile = File(...)):
    raw = await file.read(jd_input.MAX_FILE_BYTES + 1)
    try:
        result = await run_in_threadpool(jd_input.from_file, file.filename or "", raw)
    except jd_input.JdInputError as exc:
        return _error(exc)
    return asdict(result)
