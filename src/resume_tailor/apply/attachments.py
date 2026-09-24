"""Prepared-document selection and component-scoped upload verification."""

from __future__ import annotations

import asyncio
import shutil
import time
from pathlib import Path

from resume_tailor import report
from resume_tailor.apply.field_types import AttachmentOutcome, FieldObservation
from resume_tailor.apply.packet import Packet
from resume_tailor.apply.scanner import ScanSnapshot


def purpose_for(field: FieldObservation) -> str:
    name = str(field.constraints.get("name") or "")
    label = f"{field.label} {name}".casefold()
    if "cover" in label and "letter" in label:
        return "cover_letter"
    if "resume" in label or "curriculum vitae" in label or " cv" in label:
        return "resume"
    return ""


def _source(packet: Packet, purpose: str, accept: str) -> str:
    accepted = accept.casefold()
    pdf_allowed = not accepted or ".pdf" in accepted or "application/pdf" in accepted
    docx_allowed = not accepted or ".docx" in accepted or "wordprocessingml" in accepted
    prefix = "resume" if purpose == "resume" else "cover"
    if pdf_allowed and packet.artifacts.get(f"{prefix}_pdf"):
        return packet.artifacts[f"{prefix}_pdf"]
    if docx_allowed and packet.artifacts.get(f"{prefix}_docx"):
        return packet.artifacts[f"{prefix}_docx"]
    return ""


def _stage(source: str, *, purpose: str, name: str, role: str, out_dir: Path) -> Path:
    original = Path(source)
    filename = report.export_filename(name, role, suffix=original.suffix)
    if purpose == "cover_letter":
        filename = filename.replace(" Resume - ", " Cover Letter - ", 1)
    directory = out_dir / "attachments"
    directory.mkdir(parents=True, exist_ok=True)
    staged = directory / filename
    if original.resolve() != staged.resolve():
        shutil.copyfile(original, staged)
    return staged


async def upload(
    snapshot: ScanSnapshot, field: FieldObservation, packet: Packet,
    *, applicant_name: str, role: str, out_dir: Path, deadline: float,
) -> AttachmentOutcome:
    purpose = purpose_for(field)
    if not purpose:
        return AttachmentOutcome(purpose="unknown", state="unverifiable", reason="attachment purpose unknown")
    if field.current_value:
        return AttachmentOutcome(
            purpose=purpose, state="preserved", observed_filename=field.current_value,
        )
    source = _source(packet, purpose, str(field.constraints.get("accept") or ""))
    if not source:
        return AttachmentOutcome(
            purpose=purpose, state="missing_artifact",
            reason="No prepared document matches the upload's accepted formats",
        )
    expected = _stage(source, purpose=purpose, name=applicant_name, role=role, out_dir=out_dir)
    artifact = next((item for item in packet.preparation.artifacts if item.path == source), None)
    outcome = AttachmentOutcome(
        purpose=purpose, state="uploading", expected_filename=expected.name,
        artifact_sha256=artifact.sha256 if artifact else "",
    )
    try:
        target = await snapshot.locator(field)
        # This locator stays inside the same upload component even when the file
        # input is replaced after acceptance. A filename elsewhere never counts.
        component = target.locator(
            "xpath=ancestor::*[contains(@class,'upload') or "
            "contains(@class,'field') or @data-automation-id][1]"
        )
        if await component.count() != 1:
            component = None
        await target.set_input_files(str(expected), timeout=min(20000, max(1000, int((deadline-time.monotonic())*1000))))
        end = min(deadline, time.monotonic() + 20)
        while time.monotonic() < end:
            retained = ""
            try:
                retained = str(await target.evaluate("el => el.files?.[0]?.name || ''"))
            except Exception:  # noqa: BLE001 - input may have been replaced
                pass
            if retained == expected.name:
                outcome.state = "verified"
                outcome.observed_filename = retained
                return outcome
            if component is not None:
                try:
                    component_text = await component.inner_text()
                    if expected.name in component_text:
                        outcome.state = "verified"
                        outcome.observed_filename = expected.name
                        return outcome
                    if any(word in component_text.casefold() for word in ("upload failed", "file rejected", "invalid file")):
                        outcome.state = "rejected"
                        outcome.reason = "Site rejected the upload"
                        return outcome
                except Exception:  # noqa: BLE001
                    pass
            await asyncio.sleep(0.25)
        outcome.state = "unverifiable"
        outcome.reason = "Upload was attempted but the component did not confirm the filename"
    except Exception as exc:  # noqa: BLE001
        outcome.state = "unverifiable"
        outcome.reason = f"Upload action failed: {type(exc).__name__}"
    return outcome
