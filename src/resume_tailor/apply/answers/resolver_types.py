"""Records the hybrid resolver passes around: a field action, a step's resolution, its ledger."""

from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field as dc_field
from typing import Literal

from pydantic import BaseModel, Field


class FieldAction(BaseModel):
    """Targeted UI action chosen by the LLM to resolve a form blocker."""

    label: str = Field(description="Human label of the field or question")
    selector: str = Field(description="Target CSS selector on the page")
    action: Literal["select_combobox", "choose_radio", "check_options", "fill_text"]
    value: str = Field(
        description="Option text to choose or text value to fill; for check_options, the "
        "option texts to tick joined by ' | '",
    )
    rationale: str = Field(default="", description="Why this choice matches the candidate")

class StepResolution(BaseModel):
    """List of field actions to resolve the current page or step."""

    actions: list[FieldAction] = Field(default_factory=list)

@dataclass
class StepLedger:
    """What one form step has already been through, so a retry touches only the gaps.

    Keyed by selector. A control whose options were read is not opened again; one the
    model was already asked about (answered or not) is not sent again on this step.
    """

    options: dict[str, list[str]] = dc_field(default_factory=dict)
    asked: set[str] = dc_field(default_factory=set)
    done: set[str] = dc_field(default_factory=set)
    #: Model calls a control was sent in; one the model skipped is sent once more.
    tries: dict[str, int] = dc_field(default_factory=dict)
    model_unavailable: bool = False
