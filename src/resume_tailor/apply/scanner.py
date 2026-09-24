"""Read-only, frame-aware snapshots of the current application step."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from importlib import resources
from typing import Any

from resume_tailor.apply.field_types import FieldObservation


@dataclass
class ScanSnapshot:
    snapshot_id: str
    fields: list[FieldObservation] = field(default_factory=list)
    locators: dict[str, tuple[Any, str]] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)

    async def locator(self, field: FieldObservation) -> Any:
        """Resolve only inside the frame and document generation that was observed."""
        if field.snapshot_id != self.snapshot_id:
            raise ValueError("stale_snapshot")
        pair = self.locators.get(field.field_id)
        if pair is None:
            raise ValueError("unknown_field")
        frame, selector = pair
        if frame.is_detached():
            raise ValueError("frame_replaced")
        target = frame.locator(selector)
        if await target.count() != 1:
            raise ValueError("ambiguous_or_replaced_field")
        return target


async def scan(page: Any) -> ScanSnapshot:
    """Collect observations without clicks, writes, navigation, or focus changes."""
    script = resources.files("resume_tailor.apply").joinpath("dom_scan.js").read_text(encoding="utf-8")
    result = ScanSnapshot(snapshot_id=uuid.uuid4().hex)
    for frame_index, frame in enumerate(page.frames):
        try:
            raw = await frame.evaluate(script)
            if not isinstance(raw, dict):
                result.errors.append(f"frame {frame_index}: unreadable snapshot")
                continue
            generation = str(raw.get("document_generation") or "")
            frame_id = f"{frame_index}:{id(frame)}"
            for index, item in enumerate(raw.get("fields") or []):
                if not isinstance(item, dict) or not item.get("selector"):
                    continue
                selector = str(item.pop("selector"))
                field_id = f"{frame_id}:{generation}:{index}"
                options = item.get("options") or []
                for option_index, option in enumerate(options):
                    if isinstance(option, dict):
                        option["option_id"] = f"{field_id}:option:{option_index}"
                item.update(
                    snapshot_id=result.snapshot_id, field_id=field_id,
                    frame_id=frame_id, document_generation=generation,
                )
                field = FieldObservation.model_validate(item)
                result.fields.append(field)
                result.locators[field_id] = (frame, selector)
        except Exception as exc:  # noqa: BLE001 - other frames remain inspectable
            result.errors.append(f"frame {frame_index}: {type(exc).__name__}")
    return result
