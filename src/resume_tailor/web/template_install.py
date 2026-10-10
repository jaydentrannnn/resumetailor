"""Building, verifying, calibrating and installing a template from an upload or baseline."""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path

import docx

from resume_tailor import config
from resume_tailor.content import data
from resume_tailor.document import (
    calibrate,
    render,
    template_analyze,
    template_build,
    template_profile,
    template_verify,
)
from resume_tailor.document.template_profile import TemplateProfile, load_profile, save_profile
from resume_tailor.web.schemas import (
    CalibrateResponse,
    TemplateBuildResponse,
)

from . import (
    section_title_sync,
    template_info,
    template_library,
    template_library_store,
    template_ops,
    template_preview,
    template_uploads,
)


def _run_build(
    *,
    source: Path | None = None,
    output: Path | None = None,
    profile_path: Path | None = None,
) -> tuple[int, str]:
    """Shell out to `scripts/build_template.py`. Returns `(exit_code, combined_log)`.

    Kept as a named function so tests can monkeypatch it without hitting Word or the
    real build script.
    """
    script = config.PROJECT_ROOT / "scripts" / "build_template.py"
    if getattr(sys, "frozen", False) or not script.is_file():
        # The desktop build ships no scripts/, and its sys.executable is the server
        # itself: spawning it would start a second server, not a build. A non-zero
        # exit sends the caller to its in-process build.
        return 1, "build script not available here; building in-process"
    cmd = [sys.executable, str(script)]
    if source is not None:
        cmd.extend(["--from", str(source)])
    if output is not None:
        cmd.extend(["--out", str(output)])
    if profile_path is not None:
        cmd.extend(["--profile", str(profile_path)])
    # The subprocess re-imports config fresh, so without this it would build against
    # the legacy/default paths regardless of which workspace this process has active.
    active_workspace = config.active_workspace_id()
    if active_workspace is not None:
        cmd.extend(["--workspace", active_workspace])
    completed = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        cwd=str(config.PROJECT_ROOT),
        check=False,
    )
    log = (completed.stdout or "") + (completed.stderr or "")
    return completed.returncode, log

def _smoke_render(tagged: Path) -> None:
    """Render the master resume into a temp DOCX and reopen it (no PDF).

    Catches tag/XML mistakes before the staged files replace the live template.
    """
    resume = data.load()
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "smoke.docx"
        render.render(resume, template=tagged, out=out)
        # Re-open: catches OOXML that python-docx/docxtpl wrote but Word would refuse.
        docx.Document(str(out))

def _verify_staged_build(tagged: Path, profile: TemplateProfile) -> None:
    """Hold a staged, profile-based build accountable to its own mapping before it can
    replace the live template — `_smoke_render` only proves the file opens; a template
    can smoke-render cleanly and still be missing a field entirely (an unmapped
    `dates`/`location` silently drops from every job) or point a mapped field at the
    wrong span (builds and renders fine, just with the wrong text). Both are
    `TemplateBuildError`s, the same as a smoke-render failure — a staged install that
    fails either check must never reach the live slot.
    """
    issues = template_verify.verify_tagged(tagged, profile)
    issues += template_verify.verify_roundtrip(tagged, profile, data.load())
    blockers = [i for i in issues if i.blocking]
    if blockers:
        detail = "; ".join(i.message for i in blockers)
        raise template_ops.TemplateBuildError(
            f"Build verification failed: {detail}",
            log="\n".join(f"{i.code}: {i.message}" for i in blockers),
        )

def calibrate_now() -> CalibrateResponse:
    """Measure fit constants for the active template now and hot-reload them.

    Raises `FileNotFoundError` without a tagged template. A failed measurement (no PDF
    engine, a render error) comes back as ``ok=False`` with the reason in ``log``; the
    previous constants stay in effect.
    """
    tagged = config.DEFAULT_TEMPLATE_PATH
    if not tagged.exists():
        raise FileNotFoundError("Install a template before tuning page fit.")
    with template_ops.LOCK:
        try:
            result = calibrate.run(verify_anchors=True)
        except Exception as exc:  # noqa: BLE001 - reported to the UI, never swallowed
            return CalibrateResponse(
                ok=False,
                log=f"Calibration failed: {exc}",
                calibration=template_info._calibration_info(tagged),
            )
        config.reload_calibration()
        return CalibrateResponse(
            ok=True,
            log=result.log,
            warnings=list(result.warnings or []),
            calibration=template_info._calibration_info(tagged),
        )

def _maybe_calibrate(log: str, *, do_calibrate: bool) -> str:
    """Optionally measure fit constants and hot-reload them into `config`.

    Runs under `LOCK` so Word/LibreOffice is not concurrent with preview. Failures are
    appended to the log but do not undo a successful template install.
    """
    if not do_calibrate:
        return log
    with template_ops.LOCK:
        try:
            # A fresh template install changes `template_sha256`, so the render-anchor
            # check re-baselines against this workspace's own resume+template rather
            # than warning — see `calibrate.check_render_anchors`.
            result = calibrate.run(verify_anchors=True)
            config.reload_calibration()
            combined = (log + "\n\n" + result.log).strip()
            if result.warnings:
                combined += "\n" + "\n".join(f"warning: {w}" for w in result.warnings)
            return combined
        except Exception as exc:
            return (log + f"\n\nCalibration failed (template install kept): {exc}").strip()

def install_baseline(
    raw: bytes,
    filename: str,
    *,
    profile: TemplateProfile | dict,
    do_calibrate: bool = False,
    label: str | None = None,
    convert_bullets: bool = False,
) -> TemplateBuildResponse:
    """Validate an uploaded .docx, rebuild the tagged template, then swap live files.

    The upload goes through the same `prepare_upload` as analyze. When analyze cached
    prepared bytes for exactly this file (a converted .doc, say), those are used, so the
    profile's recorded hash still matches.

    Build + smoke-render happen in a temp directory and only then replace baseline,
    tagged template, and `template_profile.json` together.

    When `do_calibrate` is True, measure CHARS_PER_LINE / LINES_PER_PAGE after a successful
    install and reload them in-process (no server restart).

    After a successful install the live slot is snapshotted into the named library under
    `label` (default: upload filename stem).

    Raises `TemplateValidationError` for bad inputs and `TemplateBuildError` on build
    failure.
    """
    confirmed_sha = (
        profile.source_sha256
        if isinstance(profile, TemplateProfile)
        else str((profile or {}).get("source_sha256", ""))
    )
    cached = template_uploads._prepared_for(raw, confirmed_sha)
    if cached is not None:
        raw, filename = cached, f"{Path(filename).stem}.docx"
    else:
        prepared = template_uploads.prepare_upload(raw, filename, convert_bullets=convert_bullets)
        raw, filename = prepared.raw, prepared.filename
    template_uploads._validate_upload_bytes(raw, filename)
    resolved_label = template_library_store._normalize_library_label(
        label
        if (label or "").strip()
        else template_library_store._default_label_from_filename(filename)
    )

    with template_ops.LOCK:
        template_library_store._library_seed_if_empty()
        template_library_store._library_preserve_orphan_live()
        template_library_store._library_ensure_room_for_new(label=resolved_label)

    # `_install_with_profile` snapshots the library entry itself, inside the same
    # `LOCK` hold as its commit — see its docstring. It is not done here, in a second
    # separate acquisition, specifically to close that gap.
    response = _install_with_profile(raw, filename, profile, label=resolved_label)

    # The wizard's cached upload (for remap/preview) has now become the live template;
    # nothing further needs it, and keeping it around would just be dead weight until
    # `_prune_upload_cache`'s 24h sweep got to it.
    template_uploads.clear_upload_cache()

    # Before calibrating: the calibration digest covers the master resume, so renaming
    # its sections afterwards would mark a fresh measurement stale straight away.
    installed = load_profile()
    title_changes = section_title_sync.sync_active(installed) if installed else []
    log = response.log
    if do_calibrate:
        log = _maybe_calibrate(log, do_calibrate=True)
    return TemplateBuildResponse(
        ok=True,
        log=log,
        info=template_info.info(),
        title_changes=[list(change) for change in title_changes],
    )

def _install_with_profile(
    raw: bytes,
    filename: str,
    profile: TemplateProfile | dict,
    *,
    label: str,
) -> TemplateBuildResponse:
    """Staged profile install: build + smoke-render, then atomic commit.

    The library snapshot (`_library_record_after_install`) is taken inside this same
    `with LOCK:` block, immediately after the commit — not by the caller in a second,
    separate lock acquisition. Two concurrent installs interleaving between "commit"
    and "record" would otherwise let the second commit's bytes already be live by the
    time the first request's record step reads `config.BASELINE_TEMPLATE_PATH`, filing
    the *second* install's content under the *first* request's label.
    """
    confirmed = (
        profile
        if isinstance(profile, TemplateProfile)
        else TemplateProfile.model_validate(profile)
    )
    issues = template_analyze.validate_profile_against_doc(confirmed, raw=raw)
    blockers = [i for i in issues if i.blocking]
    if blockers:
        raise template_ops.TemplateValidationError("; ".join(i.message for i in blockers))

    with template_ops.LOCK:
        with tempfile.NamedTemporaryFile(suffix=".docx", delete=False) as tmp:
            tmp.write(raw)
            tmp_path = Path(tmp.name)
        # Everything below is wrapped in `try`/`finally` on `tmp_path` alone (not two
        # separate `tmp_path.unlink(missing_ok=True)` calls at the two points that used
        # to be tmp_path's last use) — `baseline.parent.mkdir`, the three backup
        # `read_bytes()`/`copy2()` calls, and entering `TemporaryDirectory()` all sit
        # between those two points and could raise, which previously leaked the temp
        # file into the system temp dir on any of those paths.
        try:
            try:
                docx.Document(str(tmp_path))
            except Exception as exc:
                raise template_ops.TemplateValidationError(
                    f"File is not a readable .docx: {exc}"
                ) from exc

            baseline = config.BASELINE_TEMPLATE_PATH
            tagged = config.DEFAULT_TEMPLATE_PATH
            profile_file = template_profile.profile_path()
            baseline.parent.mkdir(parents=True, exist_ok=True)

            previous_baseline: bytes | None = (
                baseline.read_bytes() if baseline.exists() else None
            )
            from resume_tailor.document import calibration_cache

            calibration_cache.remember()
            previous_tagged: bytes | None = (
                tagged.read_bytes() if tagged.exists() else None
            )
            previous_profile: bytes | None = (
                profile_file.read_bytes() if profile_file.exists() else None
            )

            if previous_baseline is not None:
                stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
                backup_dir = baseline.parent / "backups"
                backup_dir.mkdir(parents=True, exist_ok=True)
                shutil.copy2(baseline, backup_dir / f"original_export.{stamp}.docx")
                if previous_profile is not None:
                    shutil.copy2(
                        profile_file, backup_dir / f"template_profile.{stamp}.json"
                    )

            def _restore() -> None:
                """Roll baseline / tagged / profile back to their pre-install bytes."""
                if previous_baseline is not None:
                    baseline.write_bytes(previous_baseline)
                elif baseline.exists():
                    baseline.unlink()
                if previous_tagged is not None:
                    tagged.write_bytes(previous_tagged)
                elif tagged.exists():
                    tagged.unlink()
                if previous_profile is not None:
                    profile_file.write_bytes(previous_profile)
                elif profile_file.exists():
                    profile_file.unlink()

            with tempfile.TemporaryDirectory() as stage_dir:
                stage = Path(stage_dir)
                staged_src = stage / "baseline.docx"
                staged_out = stage / "main_template.docx"
                staged_profile = stage / "template_profile.json"
                shutil.copy2(tmp_path, staged_src)

                log = ""
                try:
                    save_profile(confirmed, staged_profile)
                    exit_code, log = _run_build(
                        source=staged_src,
                        output=staged_out,
                        profile_path=staged_profile,
                    )
                    if exit_code != 0 or not staged_out.exists():
                        # In-process fallback when the script seam fails or a test stub
                        # does not write the staged output path.
                        try:
                            template_build.build_from_profile(
                                staged_src, staged_out, confirmed
                            )
                            log = (
                                log + "\n(in-process profile build OK)\n"
                            ).strip()
                        except Exception as exc:
                            raise template_ops.TemplateBuildError(
                                "Profile build failed during staged install.",
                                log=(log + f"\n{exc}").strip(),
                            ) from exc

                    _smoke_render(staged_out)
                    _verify_staged_build(staged_out, confirmed)
                except template_ops.TemplateBuildError:
                    raise
                except Exception as exc:
                    raise template_ops.TemplateBuildError(
                        f"Staged build or smoke render failed: {exc}",
                        log=(log + f"\n{exc}").strip(),
                    ) from exc

                try:
                    shutil.copy2(staged_src, baseline)
                    shutil.copy2(staged_out, tagged)
                    shutil.copy2(staged_profile, profile_file)
                except Exception as exc:
                    _restore()
                    raise template_ops.TemplateBuildError(
                        f"Failed to commit staged template: {exc}",
                        log=log.strip(),
                    ) from exc

            # Snapshotted here, still under `LOCK`, rather than by the caller after this
            # function returns — see the docstring above for why the gap mattered.
            template_library._library_record_after_install(
                label=label, source_filename=Path(filename).name
            )
            template_preview.invalidate_preview()
            calibration_cache.activate()
            from resume_tailor.document.cover_template import ensure_cover_template

            ensure_cover_template(src=baseline, profile=confirmed)
            return TemplateBuildResponse(ok=True, log=log.strip(), info=template_info.info())
        finally:
            tmp_path.unlink(missing_ok=True)
