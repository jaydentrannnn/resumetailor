"""`/api/answer-memory`: the Answer book (`apply/answers/answer_book.py`).

The Profile page lists every saved answer with where it came from (your corrections,
answers typed on the page, custom answers, the AI's picks, learned question types) and
lets the student add a question, fix an answer or forget one.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from resume_tailor.apply.answers import answer_memory

router = APIRouter()


class SavedAnswersResponse(BaseModel):
    answers: list[answer_memory.SavedAnswer]


class SavedAnswerUpdate(BaseModel):
    answer: str = Field(min_length=1, max_length=answer_memory.MAX_ANSWER_CHARS)


class SavedAnswerCreate(SavedAnswerUpdate):
    label: str = Field(min_length=1, max_length=500)


@router.get("/api/answer-memory", response_model=SavedAnswersResponse)
def list_saved_answers() -> SavedAnswersResponse:
    return SavedAnswersResponse(answers=answer_memory.list_answers())


@router.post("/api/answer-memory", response_model=SavedAnswersResponse)
def add_saved_answer(body: SavedAnswerCreate) -> SavedAnswersResponse:
    """A custom answer: a question no profile field covers, and its answer."""
    if answer_memory.profile_key(body.label):
        raise HTTPException(
            status_code=400, detail="Your profile has a field for this question; fill it there."
        )
    if answer_memory.remember(body.label, body.answer, source="custom") is None:
        raise HTTPException(
            status_code=400,
            detail="Equal-opportunity, password and identity questions are never saved here.",
        )
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
