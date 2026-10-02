"""Small ATS-specific hints around the shared scanner and executor."""

from __future__ import annotations

import re
from typing import Any

from resume_tailor.apply.forms.field_catalog import classify
from resume_tailor.apply.forms.field_matcher import normalize
from resume_tailor.apply.forms.field_types import FieldObservation
from resume_tailor.apply.funnel.packet_models import Packet


class FormAdapter:
    def __init__(self, platform: str):
        self.platform = platform

    def key_for(self, field: FieldObservation) -> str:
        policy, key = classify(field)
        return key if policy == "known" else ""

    def classify(self, field: FieldObservation) -> tuple[str, str]:
        return classify(field)

    def value_for(self, field: FieldObservation, key: str, packet: Packet, fields: dict[str, str]) -> str:
        return fields.get(key, "")

    async def advance(self, page: Any) -> Any | None:
        """Only exact ordinary step controls; never submit or legal acceptance."""
        candidates = page.get_by_role(
            "button", name=re.compile(r"^\s*(next|continue|save\s*&\s*continue)\s*$", re.I),
        )
        visible = [button for button in await candidates.all() if await button.is_visible() and await button.is_enabled()]
        return visible[0] if len(visible) == 1 else None

    async def final_submit(self, page: Any) -> Any | None:
        candidates = page.get_by_role(
            "button", name=re.compile(r"^\s*(submit|submit application)\s*$", re.I),
        )
        visible = [button for button in await candidates.all() if await button.is_visible() and await button.is_enabled()]
        return visible[0] if len(visible) == 1 else None

    async def enter_application(self, page: Any, *, timeout_ms: int) -> Any:
        """Cross from the posting into the application form; most forms are the posting."""
        return page

    async def step_id(self, page: Any, fields: list[FieldObservation]) -> str:
        """URL plus visible structure identifies same-URL wizard transitions."""
        structure = "|".join(
            f"{field.frame_id}:{normalize(field.section_id)}:{normalize(field.label)}:{field.control_kind}"
            for field in fields
        )
        return f"{page.url}|{structure}"


class GreenhouseAdapter(FormAdapter):
    def __init__(self):
        super().__init__("greenhouse")

    def classify(self, field: FieldObservation) -> tuple[str, str]:
        field_id = str(field.constraints.get("id") or "")
        if re.fullmatch(r"start-year--\d+", field_id):
            return "known", "education_start_year"
        if re.fullmatch(r"end-year--\d+", field_id):
            return "known", "education_end_year"
        return classify(field)

    def value_for(self, field: FieldObservation, key: str, packet: Packet, fields: dict[str, str]) -> str:
        if key not in {"school", "degree_level", "major", "education_start_year", "education_end_year"}:
            return fields.get(key, "")
        row_id = field.repeater_row_id
        if not row_id.isdigit():
            if len(packet.education) != 1:
                return ""
            row_index = 0
        else:
            row_index = int(row_id)
        if row_index >= len(packet.education):
            return ""
        education = packet.education[row_index]
        if key == "school":
            return education.school
        if key == "degree_level":
            degree = education.degree_name or education.degree_level or education.degree
            normalized = normalize(degree)
            if normalized.startswith(("bs ", "b s ", "bachelor of science in ")):
                return "Bachelor of Science"
            if normalized.startswith(("ba ", "b a ", "bachelor of arts in ")):
                return "Bachelor of Arts"
            return degree
        if key == "major":
            return education.major
        match = re.fullmatch(r"(\d{4})(?:-\d{2})?", education.start if key == "education_start_year" else education.end)
        return match.group(1) if match else ""


class WorkdayAdapter(FormAdapter):
    def __init__(self):
        super().__init__("workday")

    def value_for(self, field: FieldObservation, key: str, packet: Packet, fields: dict[str, str]) -> str:
        if key not in {"education_start_year", "education_end_year"}:
            return fields.get(key, "")
        row = re.fullmatch(r"education-(\d+)--.*", str(field.constraints.get("id") or ""))
        if row is None or len(packet.education) != 1:
            return ""
        date = packet.education[0].start if key == "education_start_year" else packet.education[0].end
        match = re.fullmatch(r"(\d{4})(?:-\d{2})?", date)
        return match.group(1) if match else ""

    async def enter_application(self, page: Any, *, timeout_ms: int) -> Any:
        """Cross only Workday's posting/application entry controls."""
        for label in ("Apply", "Apply Manually"):
            # Once an account or application form appears, an Apply-labeled
            # action can have another meaning. Never click it in that state.
            if await page.locator(
                "input[type='password']:visible, [data-automation-id='applicationForm']:visible, "
                "[data-automation-id='jobApplicationForm']:visible"
            ).count():
                return page
            choices = page.get_by_role("button", name=re.compile(rf"^{re.escape(label)}$", re.I))
            visible = [item for item in await choices.all() if await item.is_visible() and await item.is_enabled()]
            if len(visible) != 1:
                return page
            existing = set(page.context.pages)
            await clicks.async_safe_click(visible[0], purpose="enter", timeout=timeout_ms)
            await page.wait_for_timeout(400)
            # Only a tab this page opened: a parallel fill's new tab is in the same context.
            opened = [
                item for item in page.context.pages
                if item not in existing and not item.is_closed() and await item.opener() == page
            ]
            if len(opened) == 1:
                page = opened[0]
                await page.wait_for_load_state("domcontentloaded", timeout=timeout_ms)
            elif len(opened) > 1:
                raise RuntimeError("Workday opened multiple application tabs; review the posting")
        return page


class SmartRecruitersAdapter(FormAdapter):
    """SmartRecruiters: the posting's "I'm interested" link opens the one-click form."""

    #: The posting's own entry link; ``js-smartr-oneclick`` twins apply through a Smartr
    #: account instead and are never followed.
    ENTRY = "a#st-apply:visible, a.js-oneclick:not(.js-smartr-oneclick):visible"

    def __init__(self):
        super().__init__("smartrecruiters")

    async def enter_application(self, page: Any, *, timeout_ms: int) -> Any:
        if "/oneclick-ui/" in str(page.url):
            return page  # already on the form
        links = page.locator(self.ENTRY)
        hrefs = {await link.get_attribute("href") for link in await links.all()}
        # The posting repeats its link (header, sidebar, footer): all must go one place.
        if len(hrefs) != 1:
            return page
        await clicks.async_safe_click(links.first, purpose="enter", timeout=timeout_ms)
        await page.wait_for_load_state("domcontentloaded", timeout=timeout_ms)
        return page


def for_url(url: str) -> FormAdapter:
    host = url.split("/", 3)[2].casefold() if "://" in url else ""
    if "greenhouse.io" in host or "greenhouse" in host:
        return GreenhouseAdapter()
    if "myworkdayjobs.com" in host or "workday" in host:
        return WorkdayAdapter()
    if host.endswith("smartrecruiters.com"):
        return SmartRecruitersAdapter()
    return FormAdapter("generic")
from resume_tailor.apply.driver import clicks
