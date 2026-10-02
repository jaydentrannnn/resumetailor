"""Hermetic tests for the verified Apply engine (`engine.fill_application`).

The browser, page, scanner, controls and adapter are hand-written fakes at the seams the
engine looks up (`browser`, `scanner`, `controls`, `adapters`, `form_routes`, `clicks`);
the application store is real, isolated under `tmp_path`.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import Any

import pytest

from resume_tailor import config
from resume_tailor.apply.answers import answer_memory
from resume_tailor.apply.answers import profile as profile_mod
from resume_tailor.apply.answers.profile import ApplicantProfile
from resume_tailor.apply.ats import adapters
from resume_tailor.apply.driver import browser, clicks, controls, scanner
from resume_tailor.apply.forms import engine, form_routes
from resume_tailor.apply.forms.field_types import FieldObservation, FieldOutcome
from resume_tailor.apply.funnel import packet, preparation, store, store_models
from resume_tailor.apply.funnel.packet_models import Packet
from resume_tailor.content import data
from resume_tailor.web.schemas import ApplySettings

POSTING = "https://example.com/apply"


class _Page:
    """A form page: `fields` per step, answers written into `values`."""

    def __init__(self, steps: list[list[dict[str, Any]]]):
        self.url = "about:blank"
        self.steps = steps
        self.step = 0
        self.values: dict[str, str] = {}
        self.gotos: list[str] = []

    async def goto(self, url: str, **_kwargs: Any) -> None:
        self.gotos.append(url)
        self.url = url

    async def wait_for_timeout(self, _ms: int) -> None:
        return None

    async def evaluate(self, _script: str) -> dict:
        return {}

    def observe(self) -> list[FieldObservation]:
        fields = []
        for spec in self.steps[self.step]:
            spec = dict(spec)
            field_id = spec.pop("field_id")
            current = self.values.get(field_id, spec.pop("current_value", ""))
            fields.append(FieldObservation(
                snapshot_id=f"snap-{self.step}", field_id=field_id, frame_id="main",
                document_generation="1", current_value=current, **spec,
            ))
        return fields


class _Adapter(adapters.FormAdapter):
    """Generic adapter whose advance/submit controls the test decides."""

    def __init__(self, page: _Page, *, advances: int = 0, stuck: bool = False):
        super().__init__("generic")
        self.page = page
        self.advances = advances
        self.stuck = stuck

    async def step_id(self, page: Any, fields: list[FieldObservation]) -> str:
        return f"step-{page.step}"

    async def advance(self, page: Any) -> Any | None:
        if self.advances <= 0:
            return None
        self.advances -= 1
        return "next-button"

    async def final_submit(self, page: Any) -> Any | None:
        return "submit-button"


@pytest.fixture
def engine_env(tmp_path, monkeypatch):
    """Real store under tmp; every browser/LLM seam faked. Returns a builder."""
    monkeypatch.setattr(config, "APPLICATIONS_PATH", tmp_path / "applications.json")
    monkeypatch.setattr(config, "APPLICATIONS_OUTPUT_DIR", tmp_path / "applications")
    monkeypatch.setattr(config, "OUTPUT_DIR", tmp_path / "output")
    (tmp_path / "output" / "jobs" / "job-1").mkdir(parents=True)

    monkeypatch.setattr(
        preparation, "check",
        lambda app, require_cover: preparation.PreparationEligibility(eligible=True),
    )
    monkeypatch.setattr(packet, "build_packet", lambda job_id, **_k: Packet(
        job_id=job_id, built_at="2026-01-01T00:00:00+00:00", posting_url=POSTING,
        company="Acme", role="Intern", ats="greenhouse",
        fields={"first_name": "Ada", "last_name": "Lovelace", "email": "ada@example.com"},
    ))
    monkeypatch.setattr(
        profile_mod, "load_profile", lambda: (ApplicantProfile(first_name="Ada"), False)
    )
    monkeypatch.setattr(data, "load", lambda: object())
    monkeypatch.setattr(answer_memory, "recall", lambda *_a, **_k: None)

    state: dict[str, Any] = {"applied": [], "clicks": []}

    def build(steps, *, contexts=True, target=None, route="absent", **adapter_kw):
        page = _Page(steps)
        adapter = _Adapter(page, **adapter_kw)
        state["page"] = page

        class _Connected:
            def __init__(self):
                self.contexts = [object()] if contexts else []

        @asynccontextmanager
        async def cdp():
            yield _Connected()

        async def open_page(connected, context):
            return page, "target-new"

        async def find_target(context, target_id):
            return page if target == target_id else None

        async def scan(pg):
            return scanner.ScanSnapshot(snapshot_id=f"snap-{pg.step}", fields=pg.observe())

        async def apply_value(pg, snapshot, field, value, **_kw):
            state["applied"].append((field.label, value))
            pg.values[field.field_id] = value
            return FieldOutcome(
                field_id=field.field_id, frame_id=field.frame_id, label=field.label,
                canonical_key=field.canonical_key, state="verified_filled",
                required=field.required, observed_value=value,
            )

        async def safe_click(loc, *, purpose, **_kw):
            state["clicks"].append((loc, purpose))
            if not adapter.stuck:
                page.step += 1

        async def choose_email(pg, *, deadline):
            return route

        monkeypatch.setattr(browser, "async_cdp_browser", cdp)
        monkeypatch.setattr(browser, "open_background_page", open_page)
        monkeypatch.setattr(browser, "async_find_target", find_target)
        monkeypatch.setattr(scanner, "scan", scan)
        monkeypatch.setattr(controls, "apply_value", apply_value)
        monkeypatch.setattr(clicks, "async_safe_click", safe_click)
        monkeypatch.setattr(form_routes, "choose_email_async", choose_email)
        monkeypatch.setattr(adapters, "for_url", lambda url: adapter)
        return state

    return build


def _seed_app(**overrides) -> store_models.Application:
    fields = {
        "source": "simplify", "source_job_id": "src-1", "company": "Acme",
        "role": "Intern", "posting_url": POSTING, "final_url": POSTING,
        "ats": "greenhouse", "status": "ready", "job_id": "job-1",
    }
    fields.update(overrides)
    app = store_models.Application(**fields)
    store.upsert(app)
    return app


def _run(*, fill_mode="initial", should_cancel=None, settings=None, progress=None):
    return asyncio.run(engine.fill_application(
        "src-1", settings=settings or ApplySettings(cover_letter=False),
        submit_mode=None, fill_mode=fill_mode, should_cancel=should_cancel,
        on_progress=progress,
    ))


FIRST = {"field_id": "first", "label": "First Name", "control_kind": "text", "required": True}
EMAIL = {
    "field_id": "email", "label": "Email", "control_kind": "text", "required": True,
    "constraints": {"input_type": "email"},
}


# -- end-to-end outcomes -------------------------------------------------------------


def test_fills_known_fields_and_reports_ready_for_review(engine_env):
    state = engine_env([[FIRST, EMAIL]])
    _seed_app()
    lines: list[str] = []

    result = _run(progress=lines.append)

    assert state["page"].gotos == [POSTING]
    assert state["applied"] == [("First Name", "Ada"), ("Email", "ada@example.com")]
    assert result.status == "awaiting_review"
    assert result.ready_to_submit is True
    assert result.final_step_reached is True
    assert result.handoff_reason == "Ready for review"
    assert result.browser_target_id == "target-new"
    assert {o["field_id"]: o["state"] for o in result.field_outcomes} == {
        "first": "verified_filled", "email": "verified_filled",
    }
    assert lines[0] == "Connecting to browser"
    stored = store.get("src-1")
    assert stored is not None and stored.status == "awaiting_review"
    assert store_models.FillResult.model_validate(stored.fill).ready_to_submit is True


def test_existing_answer_is_preserved_not_retyped(engine_env):
    state = engine_env([[{**FIRST, "current_value": "Ada"}, EMAIL]])
    _seed_app()

    result = _run()

    assert state["applied"] == [("Email", "ada@example.com")]
    outcomes = {o["field_id"]: o for o in result.field_outcomes}
    assert outcomes["first"]["state"] == "preserved"
    assert outcomes["first"]["answer_source"] == "existing_browser_answer"
    assert result.ready_to_submit is True


def test_unknown_required_field_blocks_readiness(engine_env):
    color = {"field_id": "color", "label": "Favorite color", "control_kind": "text",
             "required": True}
    engine_env([[FIRST, color]])
    _seed_app()

    result = _run()

    outcomes = {o["field_id"]: o for o in result.field_outcomes}
    assert outcomes["color"]["state"] == "unanswered"
    assert result.required_empty == ["Favorite color"]
    assert result.ready_to_submit is False
    assert result.handoff_reason == "Fields need review"
    assert result.status == "awaiting_review"


def test_credential_field_is_left_for_manual_review(engine_env):
    password = {"field_id": "pw", "label": "Password", "control_kind": "text",
                "constraints": {"input_type": "password"}}
    state = engine_env([[FIRST, password]])
    _seed_app()

    result = _run()

    assert ("Password", "") not in state["applied"]
    assert {o["field_id"]: o["state"] for o in result.field_outcomes}["pw"] == "manual_review"
    assert result.ready_to_submit is False


def test_advances_through_steps_with_guarded_click(engine_env):
    state = engine_env([[FIRST], [EMAIL]], advances=1)
    _seed_app()

    result = _run()

    assert state["clicks"] == [("next-button", "advance")]
    assert state["applied"] == [("First Name", "Ada"), ("Email", "ada@example.com")]
    assert result.current_step_id == "step-1"
    assert result.ready_to_submit is True


def test_step_that_does_not_advance_is_left_for_review(engine_env):
    engine_env([[FIRST]], advances=1, stuck=True)
    _seed_app()
    lines: list[str] = []

    result = _run(progress=lines.append)

    assert "Form step did not advance; leaving tab for review" in lines
    assert result.final_step_reached is False
    assert result.ready_to_submit is False


def test_missing_cover_letter_upload_is_recorded_when_requested(engine_env):
    engine_env([[FIRST, EMAIL]])
    _seed_app()

    result = _run(settings=ApplySettings(cover_letter=True))

    assert {u["purpose"]: u["state"] for u in result.uploads} == {
        "cover_letter": "not_requested"
    }
    assert result.ready_to_submit is True


# -- hand-offs and failures ----------------------------------------------------------


@pytest.mark.parametrize("route", ["ambiguous", "unchanged", "unavailable", "selected"])
def test_email_sign_in_route_hands_off_before_filling(engine_env, route):
    state = engine_env([[FIRST]], route=route)
    _seed_app()

    result = _run()

    assert state["applied"] == []
    assert result.status == "awaiting_review"
    assert "Continue fill" in result.handoff_reason
    assert store.get("src-1").status == "awaiting_review"


def test_cancel_stops_the_run_and_hands_off(engine_env):
    state = engine_env([[FIRST]])
    _seed_app()

    result = _run(should_cancel=lambda: True)

    assert state["applied"] == []
    assert result.status == "awaiting_review"
    assert result.handoff_reason == "Batch cancelled"


def test_continue_with_closed_review_tab_fails_without_navigating(engine_env):
    state = engine_env([[FIRST]], target="old-target")
    _seed_app(fill={"browser_target_id": "gone"})

    result = _run(fill_mode="continue")

    assert state["page"].gotos == []
    assert result.status == "fill_failed"
    assert "review tab is closed" in (result.error or "")
    assert store.get("src-1").status == "fill_failed"


def test_continue_resumes_the_recorded_tab(engine_env):
    state = engine_env([[FIRST, EMAIL]], target="old-target")
    _seed_app(fill={"browser_target_id": "old-target"})
    state["page"].url = POSTING

    result = _run(fill_mode="continue")

    assert state["page"].gotos == []
    assert result.browser_target_id == "old-target"
    assert result.ready_to_submit is True


def test_no_browser_context_is_a_fill_failure(engine_env):
    engine_env([[FIRST]], contexts=False)
    _seed_app()

    result = _run()

    assert result.status == "fill_failed"
    assert result.error == "No connected browser context is available"


def test_unknown_application_raises(engine_env):
    engine_env([[FIRST]])
    with pytest.raises(KeyError):
        _run()


def test_unprepared_application_raises_before_touching_the_store(engine_env, monkeypatch):
    engine_env([[FIRST]])
    _seed_app()
    monkeypatch.setattr(
        preparation, "check",
        lambda app, require_cover: preparation.PreparationEligibility(
            eligible=False, reasons=["no resume"]
        ),
    )
    with pytest.raises(RuntimeError, match="needs Prepare: no resume"):
        _run()
    assert store.get("src-1").status == "ready"


# -- pure helpers --------------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "code", "committed", "expected"),
    [
        ("+1 555-0100", "+1", True, "555-0100"),
        ("+1 555-0100", "+1", False, "+1 555-0100"),
        ("+44 20 7946", "+1", True, "+44 20 7946"),
        ("555-0100", "", True, "555-0100"),
    ],
)
def test_national_phone_value(value, code, committed, expected):
    assert engine._national_phone_value(  # noqa: SLF001
        value, code, separate_code_committed=committed
    ) == expected


@pytest.mark.parametrize(
    ("value", "kind", "expected"),
    [
        ("2027-06-01", "text", "June 1, 2027"),
        ("2027-06-01", "date", "2027-06-01"),
        ("2027-06-01", "combobox", "2027-06-01"),
        ("next summer", "text", "next summer"),
    ],
)
def test_availability_for_field(value, kind, expected):
    assert engine._availability_for_field(value, kind) == expected  # noqa: SLF001


def _observed(**kw) -> FieldObservation:
    base = {"snapshot_id": "s", "field_id": "f", "frame_id": "main",
            "document_generation": "1", "label": "First Name", "control_kind": "text"}
    return FieldObservation(**{**base, **kw})


def test_current_outcome_keeps_verified_only_when_value_agrees():
    prior = FieldOutcome(field_id="f", state="verified_filled", observed_value="Ada",
                         answer_source="profile")
    same = engine._current_outcome(_observed(current_value="Ada"), prior)  # noqa: SLF001
    changed = engine._current_outcome(_observed(current_value="Bob"), prior)  # noqa: SLF001
    assert (same.state, same.answer_source) == ("verified_filled", "profile")
    assert changed.state == "preserved"


def test_current_outcome_flags_blank_invalid_and_uncommitted():
    blank = engine._current_outcome(_observed(), None)  # noqa: SLF001
    invalid = engine._current_outcome(  # noqa: SLF001
        _observed(current_value="x", validation_messages=["Bad"]), None
    )
    pending = engine._current_outcome(  # noqa: SLF001
        _observed(control_kind="combobox", current_value="Ca", selection_state="typing"), None
    )
    assert (blank.state, blank.reason_code) == ("unanswered", "current_page_blank")
    assert (invalid.state, invalid.reason_code) == ("invalid_existing", "site_validation")
    assert (pending.state, pending.reason_code) == ("unanswered", "selection_not_committed")
