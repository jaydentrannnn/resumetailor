"""Tests for the CLI's argument handling and exit codes.

`jd.extract` and `fit.fit` are monkeypatched throughout — the CLI's job is wiring and
error presentation, and neither should require an API key or Word to verify.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from resume_tailor import config, fit as fit_mod
from resume_tailor.data import load
from resume_tailor.jd import JobRequirements, Keyword
from resume_tailor.rewrite import FabricationError

_TAILOR_PATH = Path(__file__).resolve().parents[1] / "tailor.py"


def _load_cli():
    spec = importlib.util.spec_from_file_location("tailor_cli", _TAILOR_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def cli():
    return _load_cli()


@pytest.fixture(autouse=True)
def _stub_relevance_api(cli, monkeypatch):
    """Keep every CLI test off the relevance API.

    `tailor.main` now scores bullets before fitting, so without this a test that only
    stubbed `jd.extract` and `fit.fit` would try to reach the network. An empty table means
    keyword-only ranking, which is what these tests were written against.
    """
    monkeypatch.setattr(cli.rewrite, "score_table", lambda *a, **k: {})


@pytest.fixture(autouse=True)
def _stub_expand_api(cli, monkeypatch):
    """Keep every CLI test off the expansion API.

    `tailor.main` expands experience after a successful fit. Without this stub, tests that
    only patch extract/fit would reach the network on the bonus stage.
    """
    from resume_tailor.expand import Expansion

    monkeypatch.setattr(
        cli.expand,
        "expand_experience",
        lambda *a, **k: Expansion(entries=[], warnings=[], model="stub", char_limit=2000),
    )


@pytest.fixture(autouse=True)
def _stub_facets_api(cli, monkeypatch):
    """Keep every CLI test off the facets API.

    `tailor.main` selects tech/coursework before fitting. Without this stub, tests that
    only patch extract/fit would reach the network. Budget-only truncation matches the
    `--no-facets` path these tests do not care about.
    """
    from resume_tailor import facets as facets_mod

    def fake_select(resume, requirements, **kwargs):
        """Delegate to budget_only so layout guarantees still hold."""
        return facets_mod.budget_only(
            resume,
            requirements,
            include_project_links=kwargs.get("include_project_links", True),
        )

    monkeypatch.setattr(cli.facets, "select_facets", fake_select)


@pytest.fixture
def jd_file(tmp_path) -> Path:
    path = tmp_path / "jd.txt"
    path.write_text("We need a Python engineer with retrieval experience.", encoding="utf-8")
    return path


def _requirements() -> JobRequirements:
    return JobRequirements(
        title="ML Engineer",
        seniority="entry",
        keywords=[Keyword(phrase="Python", canonical="python", importance="must_have")],
    )


def _fit_result(resume, out_path: Path) -> fit_mod.FitResult:
    bullets = {b.id: b.text for b in resume.experience[0].bullets}
    return fit_mod.FitResult(
        out_path=out_path,
        pages=1,
        pages_are_estimated=False,
        iterations=2,
        bullets_selected=len(bullets),
        bullets_total=len(resume.all_bullets()),
        bullets=bullets,
    )


def test_successful_run_prints_report_and_exits_zero(cli, jd_file, tmp_path, monkeypatch, capsys):
    resume = load()
    out = tmp_path / "tailored.docx"

    monkeypatch.setattr(cli.jd, "extract", lambda text, **kw: _requirements())
    monkeypatch.setattr(cli.jd, "verify_verbatim", lambda reqs, text: [])
    monkeypatch.setattr(cli.fit, "fit", lambda *a, **k: _fit_result(resume, out))

    code = cli.main(["--jd", str(jd_file), "--out", str(out)])

    assert code == 0
    stdout = capsys.readouterr().out
    assert "Must-have keyword coverage: 1/1" in stdout
    assert "2 iteration(s)" in stdout


def test_fit_failure_exits_one_without_printing_a_report(cli, jd_file, monkeypatch, capsys):
    """An unfittable resume must fail loudly, never emit a half-truncated summary."""
    monkeypatch.setattr(cli.jd, "extract", lambda text, **kw: _requirements())
    monkeypatch.setattr(cli.jd, "verify_verbatim", lambda reqs, text: [])

    def boom(*a, **k):
        raise fit_mod.FitError("Could not fit the resume to 1 page(s)")

    monkeypatch.setattr(cli.fit, "fit", boom)

    code = cli.main(["--jd", str(jd_file)])
    captured = capsys.readouterr()

    assert code == 1
    assert "Could not fit" in captured.err
    assert "Must-have keyword coverage" not in captured.out


def test_fabrication_error_exits_one(cli, jd_file, monkeypatch, capsys):
    monkeypatch.setattr(cli.jd, "extract", lambda text, **kw: _requirements())
    monkeypatch.setattr(cli.jd, "verify_verbatim", lambda reqs, text: [])

    def boom(*a, **k):
        raise FabricationError("introduced Kubernetes")

    monkeypatch.setattr(cli.fit, "fit", boom)

    assert cli.main(["--jd", str(jd_file)]) == 1
    assert "Kubernetes" in capsys.readouterr().err


def test_missing_jd_file_exits_one(cli, tmp_path, capsys):
    code = cli.main(["--jd", str(tmp_path / "nope.txt")])
    assert code == 1
    assert "error:" in capsys.readouterr().err


def test_paraphrased_phrases_warn_but_do_not_abort(cli, jd_file, tmp_path, monkeypatch, capsys):
    """A broken verbatim guarantee is worth flagging, but the run still produces a resume."""
    resume = load()
    out = tmp_path / "tailored.docx"

    monkeypatch.setattr(cli.jd, "extract", lambda text, **kw: _requirements())
    monkeypatch.setattr(cli.jd, "verify_verbatim", lambda reqs, text: ["machine learning"])
    monkeypatch.setattr(cli.fit, "fit", lambda *a, **k: _fit_result(resume, out))

    code = cli.main(["--jd", str(jd_file), "--out", str(out)])
    captured = capsys.readouterr()

    assert code == 0
    assert "not verbatim" in captured.err
    assert "machine learning" in captured.err


def test_pages_and_template_flags_reach_the_fit_loop(cli, jd_file, tmp_path, monkeypatch):
    resume = load()
    seen: dict = {}

    monkeypatch.setattr(cli.jd, "extract", lambda text, **kw: _requirements())
    monkeypatch.setattr(cli.jd, "verify_verbatim", lambda reqs, text: [])

    def capture(
        resume_arg, reqs, *, target_pages, template, out, max_experience, max_projects,
        semantic=None, repair_widows=True, repair_verbs=True, merge_bullets=False,
        include_project_links=True, fill_target=None,
    ):
        """Capture fit kwargs so CLI flag plumbing can be asserted."""
        seen.update(
            target_pages=target_pages,
            template=template,
            out=out,
            max_experience=max_experience,
            max_projects=max_projects,
        )
        return _fit_result(resume, tmp_path / "tailored.docx")

    monkeypatch.setattr(cli.fit, "fit", capture)

    template = tmp_path / "custom.docx"
    out = tmp_path / "custom_out.docx"
    cli.main([
        "--jd", str(jd_file), "--pages", "2", "--template", str(template), "--out", str(out),
        "--experience", "4", "--projects", "1",
    ])

    assert seen == {
        "target_pages": 2,
        "template": template,
        "out": out,
        "max_experience": 4,
        "max_projects": 1,
    }


def test_defaults_match_config(cli, jd_file, tmp_path, monkeypatch):
    resume = load()
    seen: dict = {}

    monkeypatch.setattr(cli.jd, "extract", lambda text, **kw: _requirements())
    monkeypatch.setattr(cli.jd, "verify_verbatim", lambda reqs, text: [])

    def capture(
        resume_arg, reqs, *, target_pages, template, out, max_experience, max_projects,
        semantic=None, repair_widows=True, repair_verbs=True, merge_bullets=False,
        include_project_links=True, fill_target=None,
    ):
        """Capture defaults so they stay owned by fit(), not the CLI."""
        seen.update(
            target_pages=target_pages,
            template=template,
            out=out,
            max_experience=max_experience,
            max_projects=max_projects,
            fill_target=fill_target,
        )
        return _fit_result(resume, tmp_path / "tailored.docx")

    monkeypatch.setattr(cli.fit, "fit", capture)
    cli.main(["--jd", str(jd_file)])

    assert seen["target_pages"] == config.DEFAULT_PAGE_TARGET
    assert seen["template"] is None  # render.render falls back to the default template
    # CLI builds the default export name so downloads match the contact + JD title.
    assert seen["out"] is not None
    assert seen["out"].name.endswith(".docx")
    # None, not the config value: fit() reads the default so one place owns it.
    assert seen["max_experience"] is None
    assert seen["max_projects"] is None
    assert seen["fill_target"] is None


def test_no_cache_flag_forces_reextraction(cli, jd_file, tmp_path, monkeypatch):
    resume = load()
    seen: dict = {}

    def fake_extract(text, *, known_tags=None, use_cache=True):
        seen["use_cache"] = use_cache
        seen["known_tags"] = known_tags
        return _requirements()

    monkeypatch.setattr(cli.jd, "extract", fake_extract)
    monkeypatch.setattr(cli.jd, "verify_verbatim", lambda reqs, text: [])
    monkeypatch.setattr(cli.fit, "fit", lambda *a, **k: _fit_result(resume, tmp_path / "o.docx"))

    cli.main(["--jd", str(jd_file)])
    assert seen["use_cache"] is True

    cli.main(["--jd", str(jd_file), "--no-cache"])
    assert seen["use_cache"] is False


# --------------------------------------------------------------------------------------
# Backend selection
# --------------------------------------------------------------------------------------


@pytest.fixture
def stubbed_run(cli, tmp_path, monkeypatch):
    """A run that reaches `fit.fit` without touching the network."""
    resume = load()
    monkeypatch.setattr(cli.jd, "extract", lambda *a, **k: _requirements())
    monkeypatch.setattr(cli.jd, "verify_verbatim", lambda reqs, text: [])
    monkeypatch.setattr(
        cli.fit, "fit", lambda *a, **k: _fit_result(resume, tmp_path / "o.docx")
    )
    yield
    config.resolve("claude")


def test_default_model_is_ollama_for_every_stage(cli, jd_file, stubbed_run):
    """A bare `tailor.py --jd ...` must run without an Anthropic key configured at all.

    Was `claude` until the default flipped; the point of the flip is that the zero-config
    path costs nothing, so this asserts the *whole* set of stages moved — a partial flip
    would still demand a key on the one stage left behind.
    """
    assert cli.main(["--jd", str(jd_file)]) == 0
    assert [config.provider_for(p) for p in config.PURPOSES] == ["openai"] * 5
    assert config.model_for("rewrite") == config.OLLAMA_MODEL


def test_claude_profile_still_routes_every_stage_to_anthropic(cli, jd_file, stubbed_run):
    """`--model claude` remains the way to get the old default back, unchanged."""
    assert cli.main(["--jd", str(jd_file), "--model", "claude"]) == 0
    assert [config.provider_for(p) for p in config.PURPOSES] == ["anthropic"] * 5


def test_model_flag_routes_every_stage(cli, jd_file, stubbed_run):
    assert cli.main(["--jd", str(jd_file), "--model", "ollama"]) == 0
    assert config.model_for("extract") == config.OLLAMA_MODEL
    assert config.provider_for("rewrite") == "openai"


def test_hybrid_keeps_rewriting_on_claude(cli, jd_file, stubbed_run):
    """The configuration that matters: cheap stages move, the risky one does not."""
    assert cli.main(["--jd", str(jd_file), "--model", "hybrid"]) == 0
    assert config.provider_for("score") == "openai"
    assert config.provider_for("rewrite") == "anthropic"
    assert config.provider_for("expand") == "openai"
    assert config.provider_for("facets") == "openai"


def test_rewrite_model_overrides_only_that_stage(cli, jd_file, stubbed_run):
    assert cli.main(
        ["--jd", str(jd_file), "--model", "ollama", "--rewrite-model", "claude-sonnet-5"]
    ) == 0
    assert config.provider_for("extract") == "openai"
    assert config.provider_for("rewrite") == "anthropic"


def test_expand_model_overrides_only_that_stage(cli, jd_file, stubbed_run):
    assert cli.main(
        ["--jd", str(jd_file), "--model", "claude", "--expand-model", "ollama"]
    ) == 0
    assert config.provider_for("rewrite") == "anthropic"
    assert config.provider_for("expand") == "openai"


def test_effort_flag_applies_to_every_stage(cli, jd_file, stubbed_run):
    assert cli.main(["--jd", str(jd_file), "--effort", "high"]) == 0
    assert [config.effort_for(p) for p in config.PURPOSES] == ["high"] * 5


def test_default_effort_is_lower_for_the_cheap_stages(cli, jd_file, stubbed_run):
    """Most of the bill is reasoning tokens, and neither extraction nor scoring needs
    depth — but rewriting does, so it keeps medium."""
    assert cli.main(["--jd", str(jd_file)]) == 0
    assert config.effort_for("extract") == "low"
    assert config.effort_for("score") == "low"
    assert config.effort_for("rewrite") == "medium"


def test_unknown_profile_exits_one_and_names_the_valid_ones(cli, jd_file, capsys):
    assert cli.main(["--jd", str(jd_file), "--model", "definitely-not-a-model"]) == 1
    assert "claude" in capsys.readouterr().err


def test_a_backend_failure_while_scoring_fails_the_run(cli, jd_file, tmp_path, monkeypatch, capsys):
    """Not degraded to keyword-only ranking.

    An unreachable daemon or an exhausted quota is a broken run. Silently ranking on
    keywords instead would report success while quietly producing a worse resume.
    """
    resume = load()
    monkeypatch.setattr(cli.jd, "extract", lambda *a, **k: _requirements())
    monkeypatch.setattr(cli.jd, "verify_verbatim", lambda reqs, text: [])
    monkeypatch.setattr(
        cli.fit, "fit", lambda *a, **k: _fit_result(resume, tmp_path / "o.docx")
    )

    def unreachable(*a, **k):
        raise cli.LLMError("Could not reach http://localhost:11434/v1")

    monkeypatch.setattr(cli.rewrite, "score_table", unreachable)

    assert cli.main(["--jd", str(jd_file), "--model", "ollama"]) == 1
    assert "Could not reach" in capsys.readouterr().err


def test_no_widow_repair_flag_reaches_the_fit_loop(cli, jd_file, tmp_path, monkeypatch):
    """The control half of the A/B has to actually reach the rewriter to be one."""
    resume = load()
    seen: dict = {}

    monkeypatch.setattr(cli.jd, "extract", lambda text, **kw: _requirements())
    monkeypatch.setattr(cli.jd, "verify_verbatim", lambda reqs, text: [])

    def capture(*a, repair_widows=True, repair_verbs=True, **k):
        """Record polish knobs so --no-widow-repair and --no-verb-repair are testable."""
        seen["repair_widows"] = repair_widows
        seen["repair_verbs"] = repair_verbs
        return _fit_result(resume, tmp_path / "tailored.docx")

    monkeypatch.setattr(cli.fit, "fit", capture)

    cli.main(["--jd", str(jd_file)])
    assert seen["repair_widows"] is True
    assert seen["repair_verbs"] is True

    cli.main(["--jd", str(jd_file), "--no-widow-repair"])
    assert seen["repair_widows"] is False

    cli.main(["--jd", str(jd_file), "--no-verb-repair"])
    assert seen["repair_verbs"] is False


def test_merge_flag_reaches_the_fit_loop(cli, jd_file, tmp_path, monkeypatch):
    """--merge is opt-in; the default must leave merge_bullets False."""
    resume = load()
    seen: dict = {}

    monkeypatch.setattr(cli.jd, "extract", lambda text, **kw: _requirements())
    monkeypatch.setattr(cli.jd, "verify_verbatim", lambda reqs, text: [])

    def capture(*a, merge_bullets=False, **k):
        """Record whether merging was requested."""
        seen["merge_bullets"] = merge_bullets
        return _fit_result(resume, tmp_path / "tailored.docx")

    monkeypatch.setattr(cli.fit, "fit", capture)

    cli.main(["--jd", str(jd_file)])
    assert seen["merge_bullets"] is False

    cli.main(["--jd", str(jd_file), "--merge"])
    assert seen["merge_bullets"] is True


def test_fill_target_flag_reaches_the_fit_loop(cli, jd_file, tmp_path, monkeypatch):
    """--fill-target overrides UNDERFLOW_THRESHOLD for the run."""
    resume = load()
    seen: dict = {}

    monkeypatch.setattr(cli.jd, "extract", lambda text, **kw: _requirements())
    monkeypatch.setattr(cli.jd, "verify_verbatim", lambda reqs, text: [])

    def capture(*a, fill_target=None, **k):
        """Record the fill_target override from the CLI."""
        seen["fill_target"] = fill_target
        return _fit_result(resume, tmp_path / "tailored.docx")

    monkeypatch.setattr(cli.fit, "fit", capture)

    cli.main(["--jd", str(jd_file)])
    assert seen["fill_target"] is None

    cli.main(["--jd", str(jd_file), "--fill-target", "0.88"])
    assert seen["fill_target"] == 0.88

    assert cli.main(["--jd", str(jd_file), "--fill-target", "0.5"]) == 1
