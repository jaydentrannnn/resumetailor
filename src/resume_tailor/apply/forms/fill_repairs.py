"""Correct earlier automated dates only when the applicant has not since edited them."""

from __future__ import annotations

import contextlib
from typing import Any

from resume_tailor.apply.answers import form_facts, questions, widget_actions


def previous_automated_answer(
    prior: list[dict],
    selector: str,
    frame_index: int,
    current: str,
) -> bool:
    """Only a uniquely recorded automated value is eligible for correction."""
    hits = [
        item
        for item in prior
        if item.get("selector") == selector and item.get("frame_index", 0) == frame_index
    ]
    return bool(
        len(hits) == 1
        and not hits[0].get("preserved")
        and current
        and current == hits[0].get("value")
    )


def correct_previous_answers(page: Any, prior: list[dict], facts: questions.Facts) -> list[dict]:
    repaired = []
    for item in prior:
        if item.get("preserved") or not item.get("selector"):
            continue
        label = str(item.get("label") or "")
        question = questions.Question(
            label, kind="typeahead", part=questions._part_from_text(label)
        )
        match = questions.classify(question)
        if match is None or match.key not in {
            form_facts.HIGH_SCHOOL,
            "education_start_month",
            "graduation_month",
        }:
            continue
        values = questions.answers(match, question, facts)
        if not values:
            continue
        with contextlib.suppress(Exception):
            frame_index = int(item.get("frame_index", 0))
            frame = page.frames[frame_index]
            selector = str(item["selector"])
            control = frame.locator(selector).first
            if control.get_attribute("role") != "combobox":
                continue
            current = widget_actions._selected_combobox_text(control)
            if current != str(item.get("value") or ""):
                continue
            if widget_actions._select_combobox_option(frame, selector, values[0], key=match.key):
                observed = widget_actions._selected_combobox_text(control)
                if observed != current:
                    repaired.append(
                        {
                            **item,
                            "key": match.key,
                            "value": observed,
                            "previous": current,
                            "corrected": True,
                            "reason_text": (
                                "Corrected an earlier automated answer from the resume facts"
                            ),
                        }
                    )
    return repaired
