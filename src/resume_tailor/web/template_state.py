"""One consistent template snapshot for badges, metadata, and preview identity."""

from __future__ import annotations

from . import template_defaults, template_info, template_library, template_ops, template_preview
from .schemas import TemplateBuildResponse, TemplateInfoResponse


def snapshot() -> dict:
    with template_ops.LOCK:
        library = template_library._list_library()
        return {
            "info": template_info.info().model_dump(),
            "library": library.model_dump(),
            "defaults": template_defaults.list_defaults().model_dump()["templates"],
            "preview_revision": template_preview.preview_revision(),
        }


def switched(result: TemplateBuildResponse) -> TemplateBuildResponse:
    result.snapshot = snapshot()
    result.info = TemplateInfoResponse.model_validate(result.snapshot["info"])
    return result
