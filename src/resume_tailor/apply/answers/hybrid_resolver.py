"""LLM-assisted micro-resolver for custom ATS comboboxes, floating listboxes, and validation blockers.

When the deterministic macro-pass leaves required fields empty, encounters non-standard
custom widgets (e.g. Workday/Ashby custom dropdowns), or hits a disabled 'Next' button
with on-page validation errors, this resolver extracts an accessibility snapshot of the
blockers, consults the LLM, and executes targeted actions.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import logging
import re
import threading
import time
from collections.abc import Callable
from typing import Any

from pydantic import BaseModel, Field

from resume_tailor import config
from resume_tailor.apply.answers.profile import ApplicantProfile
from resume_tailor.apply.driver import clicks
from resume_tailor.apply.funnel.packet_models import Packet
from resume_tailor.infra import llm

from . import page_blockers, resolver_types, widget_actions

_log = logging.getLogger(__name__)


_SYSTEM_PROMPT = """\
You are an expert ATS form-filling assistant. You resolve unselected comboboxes, \
radio buttons, and validation errors in complex ATS forms (Workday, Ashby, Greenhouse) \
using ONLY the applicant's profile and resume data.

Rules:
- Never fabricate work authorization or citizenship: adhere strictly to the candidate's declared profile.
- For 'How did you hear about us?' or sources, pick 'Job Board', 'LinkedIn', 'Online', or 'Other' if exact text isn't listed.
- For demographic / EEO questions (Gender, Race, Veteran, Disability): if the applicant declined or preferred not to say, choose 'Decline to self-identify', 'I prefer not to say', or similar.
- For a checkbox group, use check_options and tick only options the profile supports (a location question: the applicant's location or stated relocation preferences). When none applies, tick the one explicit 'No', 'None of the above' or 'Not Available' option on its own.
- Return exactly one action for EVERY unresolved control, using its selector. When the \
profile does not answer a control, still return an action for it with value "unknown"; \
never leave a control out.
- A value must be one of that control's listed options, copied exactly (or "unknown").
"""

#: A decision the model returns when the profile does not answer a control.
_UNKNOWN = "unknown"


class SkillPick(BaseModel):
    skill: str = Field(description="The applicant's skill, exactly as given")
    option: str | None = Field(description="The one listed option naming the same skill, or null")


class SkillPicks(BaseModel):
    picks: list[SkillPick] = Field(default_factory=list)


_SKILLS_SYSTEM_PROMPT = """\
You match a job applicant's own skills to the options a job application's Skills search \
returned. For each skill you get the options its search showed.

Pick the option that names the SAME skill: a synonym, a spelling or wording variant, the \
full name for an abbreviation or the reverse, or the skill with a qualifier that does not \
change it (for example "Python" -> "Python (Programming Language)", "ML" -> "Machine \
Learning").

Return null when no option names the same skill. Never pick a broader, narrower, or merely \
related skill ("Python" -> "Django" is wrong, "Machine Learning" -> "Deep Learning" is \
wrong): the form would then claim a skill the applicant did not list. Copy the chosen \
option's text exactly.
"""


def choose_skill_options(
    unmatched: dict[str, list[str]], *, deadline: float | None = None,
) -> dict[str, str | None]:
    """One model call for every skill whose search had no exact option.

    The model sees only skill names and option labels (plain strings). Its answers are
    kept only when they are one of the options that skill's own search showed.
    """
    if not unmatched:
        return {}
    client = llm.client_for("answer")
    if deadline is not None:
        timeout = max(1.0, min(60.0, deadline - time.monotonic()))
        if hasattr(client, "timeout"):
            client.timeout = min(float(client.timeout), timeout)
        elif hasattr(client, "with_options"):
            client = client.with_options(timeout=timeout)
    payload = [{"skill": skill, "options": options} for skill, options in unmatched.items()]
    response = client.messages.parse(
        model=config.model_for("answer"),
        max_tokens=config.max_tokens_for("answer"),
        system=_SKILLS_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": f"<skills>\n{json.dumps(payload, indent=2)}\n</skills>"}],
        output_format=SkillPicks,
    )
    parsed: SkillPicks = response.parsed_output
    chosen: dict[str, str | None] = {skill: None for skill in unmatched}
    for pick in parsed.picks:
        options = unmatched.get(pick.skill)
        if options is not None and pick.option in options:
            chosen[pick.skill] = pick.option
    return chosen


#: Extra model rounds per call for questions the model's own answers revealed; they do
#: not count against ``max_retries``.
_MAX_REVEAL_ROUNDS = 2


#: Bump when `_SYSTEM_PROMPT` or the payload changes: cached choices are keyed on it.
_RESOLVER_PROMPT_VERSION = "resolver-v1"
#: Model calls one control may be sent in before it is left for the applicant. The
#: prompt asks for a decision per control; a control the model still leaves out is sent
#: once more, alone.
_MAX_ASKS = 2
#: Guards `_IN_FLIGHT` and the cache file's read-modify-write (held only briefly).
_CHOICES_LOCK = threading.Lock()
#: Choice keys a tab is asking the model about right now. Another tab showing the same
#: question waits for that answer instead of asking again; unrelated questions never wait.
_IN_FLIGHT: dict[str, threading.Event] = {}
#: Longest a tab waits for another tab's answer to the same question.
_IN_FLIGHT_WAIT = 30.0


def _choices_path() -> Any:
    return config.CACHE_DIR / "resolver-choices.json"


def _choice_key(field: dict[str, Any], profile_digest: str) -> str:
    """Identity of one choice question: the same question, options, applicant and model
    get the same answer on every posting and every run (parallel tabs included)."""
    options = sorted(widget_actions._norm(str(option)) for option in field.get("options") or [])
    payload = "\n".join([
        _RESOLVER_PROMPT_VERSION, config.fingerprint("answer"), profile_digest,
        str(field.get("type") or ""), widget_actions._norm(str(field.get("label") or "")), *options,
    ])
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def _read_choices() -> dict[str, dict[str, str]]:
    try:
        data = json.loads(_choices_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _write_choices(new: dict[str, dict[str, str]]) -> None:
    """Merge ``new`` into the cache file (read-modify-write under `_CHOICES_LOCK`)."""
    if not new:
        return
    with _CHOICES_LOCK, contextlib.suppress(OSError):
        path = _choices_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        merged = _read_choices() | new
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(merged, indent=1, ensure_ascii=False), encoding="utf-8")
        tmp.replace(path)


def _remembered(
    keys: dict[str, str], observed: dict[str, dict[str, Any]]
) -> list[resolver_types.FieldAction]:
    """Choices already made for these very questions (another tab, an earlier run), as
    actions on this page's selectors; one whose option this form does not list is skipped."""
    known = _read_choices()
    hits = []
    for selector, key in keys.items():
        hit = known.get(key)
        if not isinstance(hit, dict) or not hit.get("action") or not hit.get("value"):
            continue
        with contextlib.suppress(Exception):
            action = resolver_types.FieldAction(
                label=str(observed[selector].get("label") or ""), selector=selector,
                action=hit["action"], value=hit["value"], rationale="same question, same answer",
            )
            if _usable(action, observed[selector]):
                hits.append(action)
    return hits


def _usable(action: resolver_types.FieldAction, field: dict[str, Any] | None) -> bool:
    """Whether ``action`` answers ``field`` with one of the options the form rendered."""
    if field is None or field.get("phone_code_menu"):
        return False
    offered = {widget_actions._norm(str(value)) for value in field.get("options", [])}
    if (
        action.action in {"select_combobox", "choose_radio"}
        and widget_actions._norm(action.value) not in offered
    ):
        return False
    if action.action == "fill_text" or action.action == "select_combobox" and field.get("type") != "combobox":
        return False
    if action.action == "check_options":
        picked = widget_actions.checked_values(action.value)
        return not (
            field.get("type") != "checkboxgroup"
            or not picked
            or any(widget_actions._norm(value) not in offered for value in picked)
            or len(picked) > 1
            and any(widget_actions._EXCLUSIVE_OPTION.match(value) for value in picked)
        )
    return field.get("type") != "checkboxgroup"


def resolve_step_blockers(
    page: Any,
    packet: Packet,
    profile: ApplicantProfile,
    *,
    max_retries: int = 2,
    on_progress: Callable[[str], None] | None = None,
    deadline: float | None = None,
    ledger: resolver_types.StepLedger | None = None,
    only_invalid: bool = False,
) -> bool:
    """Identify page blockers / errors and call the LLM to resolve them.

    With a ``ledger``, controls already resolved or already put to the model on this step
    are skipped, so a stuck field does not send the whole page round again. With
    ``only_invalid`` (after a rejected advance), only the fields the form marks invalid
    are retried, when it marks any.

    Returns True if blockers were found and resolved, False if no blockers or resolution failed.
    """
    return _StepResolver(
        page,
        packet,
        profile,
        max_retries=max_retries,
        on_progress=on_progress,
        deadline=deadline,
        ledger=ledger if ledger is not None else resolver_types.StepLedger(),
        only_invalid=only_invalid,
    ).run()


class _StepResolver:
    """One `resolve_step_blockers` call: rounds of look at the page → answer → apply."""

    def __init__(
        self,
        page: Any,
        packet: Packet,
        profile: ApplicantProfile,
        *,
        max_retries: int,
        on_progress: Callable[[str], None] | None,
        deadline: float | None,
        ledger: resolver_types.StepLedger,
        only_invalid: bool,
    ) -> None:
        self.page = page
        self.packet = packet
        self.profile = profile
        self.max_retries = max_retries
        self.on_progress = on_progress
        self.deadline = deadline
        self.ledger = ledger
        self.only_invalid = only_invalid
        self.attempt = 0
        self.reveal_rounds = 0
        # Set after an answer reveals follow-up questions: the next round covers only those.
        self.revealed: set[str] | None = None

    def log(self, msg: str) -> None:
        if self.on_progress:
            self.on_progress(f"[hybrid-resolver] {msg}")

    def run(self) -> bool:
        while self.revealed is not None or self.attempt < self.max_retries:
            if self.deadline is not None and time.monotonic() >= self.deadline:
                return False
            if self.revealed is None:
                self.attempt += 1
            outcome = self._round()
            if outcome is not None:
                return outcome
        return False

    def _round(self) -> bool | None:
        """One look at the page and one answer pass: a bool ends the call, None goes
        round again."""
        ledger = self.ledger
        info = page_blockers.extract_page_blockers(self.page)
        errors = info.get("errors") or []
        unresolved = info.get("unresolved") or []
        advance_disabled = bool(info.get("advance_disabled"))
        present = {str(f.get("selector")) for f in unresolved}

        if not errors and not unresolved and not advance_disabled:
            return True

        seen_before, unresolved = self._still_open(unresolved)
        if seen_before and unresolved:
            self.log(
                f"retrying {len(unresolved)} unfilled field(s): "
                + ", ".join(str(f.get("label") or "field")[:40] for f in unresolved)
            )
        if not unresolved:
            # Every remaining blocker was already put to the model on this step; the
            # applicant resolves it, not another full pass.
            if seen_before:
                self.log(f"{len(seen_before)} field(s) still need input; leaving them for review")
            return not errors and not advance_disabled

        self._load_options(unresolved)
        unresolved = self._select_phone_codes(unresolved)
        reserved = [
            f for f in unresolved
            if re.search(
                r"salary|compensation|race|ethnic|hispanic|latino",
                str(f.get("label") or ""), re.I,
            )
        ]
        ledger.asked |= {str(f.get("selector")) for f in reserved}  # never the model's to answer
        unresolved = [f for f in unresolved if f not in reserved]
        if not unresolved:
            # Validation errors alone give the model nothing it may act on.
            return not errors and not advance_disabled

        self.log(
            f"attempt {self.attempt}: found {len(unresolved)} unresolved controls, "
            f"{len(errors)} errors"
        )
        answered = self._answer(unresolved, errors)
        if answered is None:
            return False
        actions, responded, observed = answered
        if not actions:
            if not responded:
                self.log("LLM returned no actions")
            return None
        executed = self._execute(actions)
        return self._after_actions(executed, present, observed)

    def _still_open(
        self, unresolved: list[dict[str, Any]]
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """(blockers this step already handled, the ones still to work on)."""
        handled = self.ledger.asked | self.ledger.done
        seen_before = [f for f in unresolved if str(f.get("selector")) in handled]
        unresolved = [f for f in unresolved if str(f.get("selector")) not in handled]
        if self.revealed is not None:
            # Not marked invalid yet: the form validates them only on Save and Continue.
            unresolved = [f for f in unresolved if str(f.get("selector")) in self.revealed]
            self.revealed = None
        elif self.only_invalid and any(f.get("invalid") for f in unresolved):
            unresolved = [f for f in unresolved if f.get("invalid")]
        return seen_before, unresolved

    def _load_options(self, unresolved: list[dict[str, Any]]) -> None:
        """Only let the model choose from options actually rendered by this form."""
        page, ledger = self.page, self.ledger
        for field in unresolved:
            if field.get("type") != "combobox" or not field.get("selector"):
                continue
            selector = str(field["selector"])
            if selector in ledger.options:
                field["options"] = ledger.options[selector]
                continue
            try:
                trigger = page.locator(selector).first
                if widget_actions._is_upload_widget(trigger):
                    field["options"] = []
                    continue
                clicks.safe_click(trigger, purpose="select", timeout=3000)
                choices = widget_actions._menu_choices(page, trigger)
                all_options = [
                    choice.inner_text().strip() for choice in choices if choice.is_visible()
                ]
                trigger.press("Escape")
            except Exception:  # noqa: BLE001
                all_options = []
            field["options"] = all_options[:50]
            ledger.options[selector] = field["options"]

    def _select_phone_codes(self, unresolved: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Answer phone calling-code menus from the profile; the rest stay unresolved."""
        profile = self.profile
        for field in unresolved:
            options = field.get("options") or []
            field["phone_code_menu"] = (
                sum(bool(re.search(r"\+\d{1,4}\b", str(o))) for o in options) >= 2
            )
            if field["phone_code_menu"]:
                field["phone_match"] = widget_actions._phone_option(
                    [str(o) for o in options], profile.phone_country_code,
                    profile.phone_country_region,
                )

        resolved_phone: set[str] = set()
        for field in unresolved:
            if field.get("phone_code_menu") and field.get("phone_match"):
                selected = widget_actions._select_combobox_option(
                    self.page, str(field["selector"]), profile.phone_country_code,
                    key="phone_country_code", phone_region=profile.phone_country_region,
                )
                if selected:
                    resolved_phone.add(str(field["selector"]))
                    self.log(f"selected phone calling code for {field.get('label')}")
        self.ledger.done |= resolved_phone
        return [field for field in unresolved if str(field.get("selector")) not in resolved_phone]

    # -- answering ---------------------------------------------------------------------

    def _answer(
        self, unresolved: list[dict[str, Any]], errors: list[Any]
    ) -> tuple[list[resolver_types.FieldAction], set[str], dict[str, dict[str, Any]]] | None:
        """(actions to apply, selectors the model answered, the controls by selector);
        None when the model call failed."""
        ledger = self.ledger
        safe_profile = self.profile.model_dump(
            exclude={"workday_password", "workday_email"},
            mode="json",
        )
        profile_digest = hashlib.sha256(
            json.dumps(safe_profile, sort_keys=True).encode("utf-8")
        ).hexdigest()
        observed = {str(item.get("selector")): item for item in unresolved if item.get("selector")}
        keys = {
            selector: _choice_key(field, profile_digest) for selector, field in observed.items()
        }

        actions, answered = self._recall(keys, observed)
        if actions:
            self.log(f"reusing {len(actions)} earlier answer(s) to the same question(s)")
        to_ask = [field for field in unresolved if str(field.get("selector")) not in answered]
        asked = self._ask_model(to_ask, errors, keys, observed, safe_profile)
        if asked is None:
            return None
        model_actions, responded = asked

        # A control the model decided on (an option, "unknown", or an option the form does
        # not list) is final on this step; one it left out entirely goes into the next,
        # smaller call, up to `_MAX_ASKS` calls.
        answered |= responded
        for field in to_ask:
            selector = str(field.get("selector") or "")
            if selector:
                ledger.tries[selector] = ledger.tries.get(selector, 0) + 1
        ledger.asked |= {
            selector for selector in observed
            if selector in answered or ledger.tries.get(selector, 0) >= _MAX_ASKS
        }
        actions += model_actions
        return actions, responded, observed

    def _recall(
        self, keys: dict[str, str], observed: dict[str, dict[str, Any]]
    ) -> tuple[list[resolver_types.FieldAction], set[str]]:
        """Earlier answers to these questions, waiting briefly for any another tab is
        asking about right now."""
        actions = _remembered(keys, observed)
        answered = {action.selector for action in actions}
        # A question another tab is asking right now: wait for its answer rather than ask
        # the same thing twice (parallel fills of one employer's postings, 2026-09).
        with _CHOICES_LOCK:
            waiting = {
                selector: _IN_FLIGHT[key] for selector, key in keys.items()
                if selector not in answered and key in _IN_FLIGHT
            }
        if waiting:
            wait_until = time.monotonic() + _IN_FLIGHT_WAIT
            if self.deadline is not None:
                wait_until = min(wait_until, self.deadline - 5)
            for event in set(waiting.values()):
                event.wait(max(0.0, wait_until - time.monotonic()))
            actions = _remembered(keys, observed)
            answered = {action.selector for action in actions}
        return actions, answered

    def _ask_model(
        self,
        to_ask: list[dict[str, Any]],
        errors: list[Any],
        keys: dict[str, str],
        observed: dict[str, dict[str, Any]],
        safe_profile: dict[str, Any],
    ) -> tuple[list[resolver_types.FieldAction], set[str]] | None:
        """Put `to_ask` to the model while marking those questions in flight; (usable
        actions, selectors it answered), or None when the call failed."""
        mine: dict[str, threading.Event] = {}
        with _CHOICES_LOCK:
            for field in to_ask:
                key = keys[str(field.get("selector"))]
                if key not in _IN_FLIGHT:
                    mine[key] = _IN_FLIGHT[key] = threading.Event()
        model_actions: list[resolver_types.FieldAction] = []
        responded: set[str] = set()
        try:
            if to_ask:
                resolution = self._call_model(to_ask, errors, safe_profile)
                if resolution is None:
                    return None
                asked_now = {str(field.get("selector")) for field in to_ask}
                responded = {
                    action.selector for action in resolution.actions
                    if action.selector in asked_now
                }
                unknown = sorted(
                    str(observed[action.selector].get("label") or action.selector)[:40]
                    for action in resolution.actions
                    if action.selector in asked_now
                    and widget_actions._norm(action.value) == _UNKNOWN
                )
                if unknown:
                    self.log(
                        f"the profile does not answer {len(unknown)} question(s): "
                        f"{', '.join(unknown)}"
                    )
                model_actions = [
                    action for action in resolution.actions
                    if action.selector in asked_now
                    and _usable(action, observed.get(action.selector))
                ]
                _write_choices({
                    keys[action.selector]: {
                        "action": action.action, "value": action.value,
                        "label": str(observed[action.selector].get("label") or "")[:200],
                    }
                    for action in model_actions
                    if action.action in {"select_combobox", "choose_radio", "check_options"}
                })
        finally:
            with _CHOICES_LOCK:
                for key, event in mine.items():
                    _IN_FLIGHT.pop(key, None)
                    event.set()
        return model_actions, responded

    def _call_model(
        self, to_ask: list[dict[str, Any]], errors: list[Any], safe_profile: dict[str, Any]
    ) -> resolver_types.StepResolution | None:
        user_content = [
            f"<unresolved_controls>\n{json.dumps(to_ask, indent=2)}\n</unresolved_controls>",
            f"<validation_errors>\n{json.dumps(errors, indent=2)}\n</validation_errors>",
            f"<candidate_profile>\n{json.dumps(safe_profile, indent=2)}\n</candidate_profile>",
            f"<packet_fields>\n{json.dumps(self.packet.fields, indent=2)}\n</packet_fields>",
        ]
        try:
            client = llm.client_for("answer")
            if self.deadline is not None:
                timeout = max(1.0, min(60.0, self.deadline - time.monotonic()))
                if hasattr(client, "timeout"):
                    client.timeout = min(float(client.timeout), timeout)
                elif hasattr(client, "with_options"):
                    client = client.with_options(timeout=timeout)
            response = client.messages.parse(
                model=config.model_for("answer"),
                max_tokens=config.max_tokens_for("answer"),
                system=_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": "\n\n".join(user_content)}],
                output_format=resolver_types.StepResolution,
            )
            resolution: resolver_types.StepResolution = response.parsed_output
            return resolution
        except llm.LLMError as exc:
            status = re.search(r"\bHTTP (429|5\d\d)\b", str(exc))
            if status:
                self.ledger.model_unavailable = True
                self.log(
                    f"Autofill model unavailable (HTTP {status.group(1)}); leaving "
                    f"{len(to_ask)} question(s) for review"
                )
            else:
                self.log(f"LLM call failed: {exc}")
            return None
        except Exception as exc:  # noqa: BLE001
            self.log(f"LLM call failed: {exc}")
            return None

    # -- applying ----------------------------------------------------------------------

    def _execute(self, actions: list[resolver_types.FieldAction]) -> int:
        executed = 0
        for action in actions:
            self.log(f"executing action: {action.action} on '{action.label}' -> '{action.value}'")
            ok = widget_actions.execute_action(self.page, action)
            if not ok:
                # A choice that did not stick (a list still opening, a repaint) is
                # retried once rather than left blank on this tab only.
                self.page.wait_for_timeout(500)
                ok = widget_actions.execute_action(self.page, action)
            if ok:
                executed += 1
                self.ledger.done.add(action.selector)

        self.log(f"successfully applied {executed}/{len(actions)} actions")
        self.page.wait_for_timeout(1000)
        return executed

    def _after_actions(
        self, executed: int, present: set[str], observed: dict[str, dict[str, Any]]
    ) -> bool | None:
        """True once the step's blockers are gone; None to go round again."""
        ledger = self.ledger
        updated = page_blockers.extract_page_blockers(self.page)
        # An answer can reveal a follow-up ("If hired, can you provide proof of
        # eligibility?" after "legally permitted to work" = Yes). Workday shows no error
        # for it until Save and Continue, so look for it here rather than stop early.
        known = present | ledger.asked | ledger.done
        new = {
            str(f.get("selector")) for f in updated.get("unresolved") or []
            if f.get("selector") and str(f.get("selector")) not in known
        }
        if executed and new and self.reveal_rounds < _MAX_REVEAL_ROUNDS:
            self.reveal_rounds += 1
            self.revealed = new
            self.log(f"answer revealed {len(new)} new question(s)")
            return None
        skipped = [
            f for f in updated.get("unresolved") or []
            if str(f.get("selector")) in observed
            and str(f.get("selector")) not in ledger.asked | ledger.done
        ]
        if skipped and self.attempt < self.max_retries:
            # The page shows no error yet, but a question the model skipped is still
            # blank: ask about it again rather than call the step cleared.
            return None
        if not updated.get("advance_disabled") and not updated.get("errors"):
            self.log("validation blockers cleared!")
            return True
        return None
