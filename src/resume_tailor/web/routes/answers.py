"""`/api/answer-memory`: the answers remembered from review corrections (P3-A).

The Profile page lists them with where they came from and when, and lets the student
fix or forget one. New answers are only ever added by a verified correction in the
review flow (`apply/review.correct`), never through this API.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from resume_tailor.apply import answer_memory

router = APIRouter()


class SavedAnswersResponse(BaseModel):
    answers: list[answer_memory.SavedAnswer]


class SavedAnswerUpdate(BaseModel):
    answer: str = Field(min_length=1, max_length=answer_memory.MAX_ANSWER_CHARS)


@router.get("/api/answer-memory", response_model=SavedAnswersResponse)
def list_saved_answers() -> SavedAnswersResponse:
    return SavedAnswersResponse(answers=answer_memory.list_answers())


@router.put("/api/answer-memory/{answer_id}", response_model=answer_memory.SavedAnswer)
def update_saved_answer(answer_id: int, body: SavedAnswerUpdate) -> answer_memory.SavedAnswer:
    try:
        return answer_memory.update(answer_id, body.answer)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="No such saved answer.") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/api/answer-memory/{answer_id}", response_model=SavedAnswersResponse)
def delete_saved_answer(answer_id: int) -> SavedAnswersResponse:
    try:
        answer_memory.delete(answer_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="No such saved answer.") from exc
    return SavedAnswersResponse(answers=answer_memory.list_answers())
