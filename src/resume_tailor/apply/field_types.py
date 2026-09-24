"""Backward-compatible records for observed application controls and their outcomes."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


ControlKind = Literal[
    "text", "textarea", "date", "number", "native_select", "combobox",
    "multiselect", "radio_group", "checkbox", "checkbox_group", "file", "unsupported",
]
OutcomeState = Literal[
    "verified_filled", "preserved", "unanswered", "ambiguous", "invalid_existing",
    "manual_review", "failed",
]


class ObservedOption(BaseModel):
    option_id: str
    label: str
    value: str = ""
    enabled: bool = True
    placeholder: bool = False
    selected: bool = False


class FieldObservation(BaseModel):
    snapshot_id: str
    field_id: str
    frame_id: str
    document_generation: str
    section_id: str = ""
    repeater_row_id: str = ""
    label: str = ""
    help_text: str = ""
    canonical_key: str = ""
    control_kind: ControlKind = "unsupported"
    required: bool = False
    enabled: bool = True
    visible: bool = True
    current_value: str = ""
    selection_state: str = ""
    options: list[ObservedOption] = Field(default_factory=list)
    validation_messages: list[str] = Field(default_factory=list)
    constraints: dict[str, Any] = Field(default_factory=dict)


class FieldOutcome(BaseModel):
    field_id: str
    frame_id: str = ""
    step_id: str = ""
    label: str = ""
    canonical_key: str = ""
    state: OutcomeState
    required: bool = False
    observed_value: str = ""
    answer_source: str = ""
    reason_code: str = ""
    reason_text: str = ""
    evidence: dict[str, Any] = Field(default_factory=dict)
    observed_at: str = ""


class AttachmentOutcome(BaseModel):
    purpose: str
    state: Literal[
        "not_requested", "preserved", "uploading", "verified", "missing_artifact",
        "rejected", "unverifiable",
    ]
    expected_filename: str = ""
    observed_filename: str = ""
    artifact_sha256: str = ""
    reason: str = ""
