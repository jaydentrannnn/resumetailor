"""The two-line bullet cap and the most recent job's protected lead bullet."""

from __future__ import annotations

from resume_tailor import config
from resume_tailor.content.data import Bullet, Experience, Project
from resume_tailor.document import render
from resume_tailor.pipeline import fit_lines, fit_selection, fit_types, followups, rewrite_prompts
from resume_tailor.pipeline.jd import JobRequirements, Keyword

CAP = fit_types._TARGET_LINES_PER_BULLET


def _requirements() -> JobRequirements:
    return JobRequirements(
        title="Software Engineer",
        seniority="entry",
        keywords=[Keyword(phrase="Python", canonical="python", importance="must_have")],
    )


def _fit(lines: int, last_fill: float = 0.9) -> render.LineFit:
    return render.LineFit(lines, last_fill, float(config.CHARS_PER_LINE))


def test_overlong_targets_cap_only_bullets_past_the_line_target():
    texts = {"long": "a", "ok": "b", "unknown": "c"}
    sources = {bid: Bullet(id=bid, text="x", tags=["python"]) for bid in ("long", "ok")}
    layout = {"long": _fit(CAP + 1), "ok": _fit(CAP), "unknown": _fit(CAP + 2)}

    targets = fit_lines._overlong_targets(texts, sources, layout)

    ceiling = int(CAP * config.CHARS_PER_LINE - config.WIDOW_SAFETY)
    assert targets == {"long": (0, ceiling)}, "full last lines count too; no source, no cut"


def test_pullbacks_take_every_overlong_bullet_first_even_past_count():
    width = config.CHARS_PER_LINE
    texts = {
        "near_widow": "a" * (width + int(width * 0.1)),
        "long1": "a" * (CAP * width + int(width * 0.9)),
        "long2": "a" * (CAP * width + 2 * width),
    }
    sources = {bid: Bullet(id=bid, text="x", tags=["python"]) for bid in texts}

    picked = fit_selection._choose_pullbacks(texts, sources, _requirements(), None, {}, count=1)

    assert set(picked) == {"long1", "long2"}
    assert all(c == CAP * width - config.WIDOW_SAFETY for c in picked.values())


def _experience(company: str, end: str, ids: list[str]) -> Experience:
    return Experience(
        company=company, title="Intern", start="2020-01", end=end,
        bullets=[Bullet(id=i, text=f"{company} {i}.", tags=["python"]) for i in ids],
    )


def test_drops_spare_the_most_recent_jobs_lead_bullet():
    recent = _experience("Recent", "2026-08", ["r1", "r2"])
    older = _experience("Older", "2021-01", ["o1", "o2"])
    project = Project(id="p", name="P", bullets=[Bullet(id="p1", text="P.", tags=["python"])])
    entries = [recent, older, project]
    texts = {"r1": "a" * 10, "r2": "a" * 10, "o1": "a" * 10, "o2": "a" * 10, "p1": "a"}
    sources = {b.id: b for e in entries for b in e.bullets}
    # r1 scores lowest of all; it still must not be the bullet that goes.
    semantic = {"r1": 0.0, "r2": 9.0, "o1": 5.0, "o2": 6.0}

    assert fit_selection._lead_bullet(entries, texts) == "r1"
    doomed = fit_selection._choose_drops(
        entries, texts, sources, _requirements(), semantic, {}, overflow=1
    )
    assert doomed == ["o1"]


def test_lead_bullet_is_dropped_only_when_nothing_else_can_be():
    recent = _experience("Recent", "2026-08", ["r1", "r2"])
    texts = {"r1": "a", "r2": "a"}
    sources = {b.id: b for b in recent.bullets}
    semantic = {"r1": 9.0, "r2": 0.0}

    doomed = fit_selection._choose_drops(
        [recent], texts, sources, _requirements(), semantic, {}, overflow=1
    )
    assert doomed == ["r2"], "the per-entry floor keeps one bullet; r2 is the only option"


class _Messages:
    def __init__(self, reply):
        self._reply = reply

    def parse(self, **_kwargs):
        reply = self._reply

        class _Response:
            parsed_output = reply
            stop_reason = "end_turn"

        return _Response()


class _Client:
    def __init__(self, reply):
        self.messages = _Messages(reply)


def test_number_floor_lets_a_cap_keep_only_the_figures_the_draft_kept(monkeypatch):
    source = Bullet(
        id="a", text="Fine-tuned Qwen on 9,000 examples with 16K context on four GPUs.",
        tags=["qwen"],
    )
    current = "Fine-tuned Qwen on 9,000 examples with long context on GPUs, which ran long."
    reply = rewrite_prompts.RewriteResult(
        bullets=[rewrite_prompts.RewrittenBullet(id="a", text="Fine-tuned Qwen on 9,000 examples.")]
    )
    monkeypatch.setattr(config, "anthropic_api_key", lambda: "test-key")
    monkeypatch.setattr(followups.llm, "client_for", lambda purpose: _Client(reply))

    master_only, fixed, _, _ = followups._polish(
        {"a": current}, {"a": source}, _requirements(), repair_widows=False,
        repair_verbs=False, targets={"a": (0, 60)},
    )
    assert fixed == 0 and master_only["a"] == current, "16K is in the master: rejected"

    capped, fixed, _, _ = followups._polish(
        {"a": current}, {"a": source}, _requirements(), repair_widows=False,
        repair_verbs=False, targets={"a": (0, 60)}, number_floor={"a": current},
    )
    assert fixed == 1 and capped["a"] == "Fine-tuned Qwen on 9,000 examples."


def test_a_length_repair_keeps_the_opener_the_verb_pass_chose(monkeypatch):
    """The master opens with "Built" like two other page bullets; a cut must not restore it."""
    sources = {
        bid: Bullet(id=bid, text=f"Built a {bid} pipeline in Python for search.", tags=["python"])
        for bid in ("a", "b", "c")
    }
    texts = {
        "a": "Built a a pipeline in Python for search.",
        "b": "Built a b pipeline in Python for search.",
        "c": "Engineered a c pipeline in Python for search, with retries, logging and docs.",
    }
    reply = rewrite_prompts.RewriteResult(
        bullets=[rewrite_prompts.RewrittenBullet(id="c", text="Built a c pipeline in Python.")]
    )
    monkeypatch.setattr(config, "anthropic_api_key", lambda: "test-key")
    monkeypatch.setattr(followups.llm, "client_for", lambda purpose: _Client(reply))

    out, fixed, _, _ = followups._polish(
        texts, sources, _requirements(), repair_widows=False, repair_verbs=False,
        targets={"c": (0, 60)},
    )
    assert fixed == 1 and out["c"] == "Engineered a c pipeline in Python."


def test_a_length_repair_that_cannot_keep_its_opener_is_discarded():
    texts = {"a": "Built X.", "b": "Built Y.", "c": "Engineered Z with care."}
    assert followups._keep_opener(texts, "c", "Using Python, built Z.") == "Using Python, built Z."
    texts["d"] = "Using Go, shipped W."
    assert followups._keep_opener(texts, "c", "Using Python, built Z.") is None
