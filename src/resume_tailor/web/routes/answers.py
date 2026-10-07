"""`/api/answer-memory`: the answers remembered from review corrections (P3-A).

The Profile page lists them with where they came from and when, and lets the student
fix or forget one. New answers are only ever added by a verified correction in the
review flow (`apply/review.correct`), never through this API.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from resume_tailor.apply.answers import answer_memory, hybrid_resolver

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


class AIChoice(BaseModel):
    key: str
    label: str
    answer: str


class AIChoicesResponse(BaseModel):
    choices: list[AIChoice]


@router.get("/api/answer-memory/ai-choices", response_model=AIChoicesResponse)
def list_ai_choices() -> AIChoicesResponse:
    """Dropdown/radio picks the autofill model made, which fills reuse until forgotten."""
    return AIChoicesResponse(choices=[AIChoice(**row) for row in hybrid_resolver.list_choices()])


@router.delete("/api/answer-memory/ai-choices/{key}", response_model=AIChoicesResponse)
def forget_ai_choice(key: str) -> AIChoicesResponse:
    if not hybrid_resolver.forget_choice(key):
        raise HTTPException(status_code=404, detail="No such saved choice.")
    return list_ai_choices()
