"""Facet-selection models: the model's structured reply and the resolved result."""

from __future__ import annotations

from dataclasses import dataclass, field

from pydantic import BaseModel, Field


class ProjectTech(BaseModel):
    """Chosen tech labels for one project, keyed by project id."""

    id: str
    #: Selected labels, best-first. Must be drawn from that project's pool.
    tech: list[str] = Field(default_factory=list)
    #: Optional renames: original pool label -> JD wording. Guarded in code.
    renamed: dict[str, str] = Field(default_factory=dict)

class FacetSelection(BaseModel):
    """Raw model output before budget truncation and rename validation."""

    projects: list[ProjectTech] = Field(default_factory=list)
    #: Selected coursework titles, best-first. Must be drawn from the education pool.
    coursework: list[str] = Field(default_factory=list)
    #: Optional renames: exact skill item (any group) -> posting wording. Guarded in code.
    #: Flat map rather than per-group like `ProjectTech.renamed` because nothing is
    #: *selected* for skills — only wording may change — so there is no per-group id to
    #: key on, and items are unique across groups in practice.
    skill_renames: dict[str, str] = Field(default_factory=dict)

@dataclass
class FacetResult:
    """Validated, budget-trimmed facet choices ready to apply to a resume."""

    projects: dict[str, list[str]] = field(default_factory=dict)
    coursework: list[str] = field(default_factory=list)
    coursework_pool: list[str] = field(default_factory=list)
    #: One entry per `resume.skills` group, same order. Positional (not keyed by label)
    #: since `SkillGroup` has no id and `label` is not guaranteed unique.
    skills: list[list[str]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
