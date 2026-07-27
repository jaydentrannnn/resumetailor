"""Regression tests for the template-rendering layer.

Every test here corresponds to a bug that actually shipped into a generated document
during development. All three produced files that were structurally well-formed XML and
passed a naive "does it parse" check, yet were rejected by Word or silently lost content
— so they are checked against the rendered XML, not against a parse.

These run without Word: they inspect the .docx package directly rather than converting to
PDF, so they stay fast and work on any platform.
"""

from __future__ import annotations

import zipfile

import pytest
from lxml import etree

from resume_tailor import config, data, render

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


@pytest.fixture(scope="module")
def rendered(tmp_path_factory) -> bytes:
    """Render the full master resume and return its document.xml."""
    if not config.DEFAULT_TEMPLATE_PATH.exists():
        pytest.skip("template not built; run scripts/build_template.py")
    out = tmp_path_factory.mktemp("render") / "out.docx"
    render.render(data.load(), out=out)
    return zipfile.ZipFile(out).read("word/document.xml")


def test_document_is_well_formed(rendered):
    etree.fromstring(rendered)


def test_no_python_repr_leaked_into_document(rendered):
    """`{{ group.items }}` resolved to dict.items and injected `<built-in method ...>`.

    Jinja tries attribute lookup before key lookup, so any context key that collides with
    a dict attribute renders as a method repr. The angle brackets became bogus XML
    elements, which Word rejected with a generic "cannot open the file".
    """
    text = rendered.decode("utf-8")
    assert "<built-in" not in text
    assert "method items" not in text
    assert "object at 0x" not in text


def test_ampersands_survive(rendered):
    """An unescaped "&" was swallowed as a malformed XML entity.

    "Tools & Languages" rendered as "Tools  Languages" until autoescape was enabled.
    """
    root = etree.fromstring(rendered)
    body_text = "".join(t.text or "" for t in root.iter(f"{W}t"))
    assert "Tools & Languages" in body_text
    assert "hybrid retrieval & reranking" in body_text


def test_project_links_render_as_real_hyperlinks(rendered):
    """A plain `{{ }}` nested the link's run inside a `<w:t>`, which silently drops it.

    `w:t` may only contain characters, so the hyperlink vanished on read-back. The fix is
    docxtpl's `{{r }}` RichText tag.
    """
    root = etree.fromstring(rendered)
    links = list(root.iter(f"{W}hyperlink"))
    assert links, "no hyperlinks rendered"

    # A hyperlink must never be nested inside a text element.
    for t in root.iter(f"{W}t"):
        assert t.find(f".//{W}hyperlink") is None, "hyperlink nested inside w:t"

    body_text = "".join(t.text or "" for t in root.iter(f"{W}t"))
    assert "Github" in body_text


def test_each_project_keeps_its_own_url(tmp_path):
    """Baking one hyperlink into the template pointed every project at the same repo.

    Checks resolved targets, not relationship ids: distinct ids can still resolve to the
    same URL, which is precisely the bug.
    """
    if not config.DEFAULT_TEMPLATE_PATH.exists():
        pytest.skip("template not built; run scripts/build_template.py")

    out = tmp_path / "out.docx"
    resume = data.load()
    render.render(resume, out=out)

    z = zipfile.ZipFile(out)
    root = etree.fromstring(z.read("word/document.xml"))
    rels = etree.fromstring(z.read("word/_rels/document.xml.rels"))
    target_of = {r.get("Id"): r.get("Target") for r in rels}

    R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
    targets = {target_of.get(h.get(f"{R}id")) for h in root.iter(f"{W}hyperlink")}

    expected = {p.url for p in resume.projects if p.url}
    assert expected <= targets, f"missing project URLs: {expected - targets}"


def test_bullet_spacing_is_normalised_within_each_section(rendered):
    """Every bullet in a section must share one spacing, the tightest source variant.

    The source resume mixes single-spaced and 1.15-spaced bullets *within* the experience
    section. Cloning the looser one inflated the document by roughly 15% of a line per
    bullet and pushed a one-page resume onto two.

    Normalisation is deliberately per-section, not global: experience and projects are
    visually distinct in the source, and flattening them together would change the look
    more than the loop actually requires.
    """
    root = etree.fromstring(rendered)

    section = None
    by_section: dict[str, set] = {}
    for p in root.iter(f"{W}p"):
        text = "".join(t.text or "" for t in p.iter(f"{W}t")).strip()
        if text in ("EDUCATION", "WORK EXPERIENCES", "PROJECTS", "SKILLS"):
            section = text
            continue
        if p.find(f".//{W}numPr") is None or section is None:
            continue
        pPr = p.find(f"{W}pPr")
        spacing = pPr.find(f"{W}spacing") if pPr is not None else None
        ind = pPr.find(f"{W}ind") if pPr is not None else None
        by_section.setdefault(section, set()).add(
            (
                spacing.get(f"{W}line") if spacing is not None else None,
                ind.get(f"{W}right") if ind is not None else None,
            )
        )

    assert by_section, "no bullets found in any section"
    for name, variants in by_section.items():
        assert len(variants) == 1, f"{name} has inconsistent bullet spacing: {variants}"
