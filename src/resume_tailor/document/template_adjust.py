"""Quick adjustments: margins, font, per-field bold/italic/underline, separators,
bullets and link look, without Word.

Edits the Edit-layout-in-Word skeleton (`template_skeleton.py`) the way a person would in
Word, so the result goes through the same read-back (`skeleton_parse.py`) and template
wizard as a Word edit. The layout file stays the one source of formatting: there are no
override settings stacked on top of a template. The exceptions are what the document
cannot hold (separators the renderer writes, the bullet marker the build applies, the
link look): those change `TemplateStyle`, which travels with the layout file's meta.
"""

from __future__ import annotations

import io

import docx
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches, Pt
from lxml import etree
from pydantic import BaseModel, Field, field_validator

from resume_tailor.document import adjust_separators, docx_text, skeleton_tokens, template_style
from resume_tailor.document.skeleton_tokens import TOKEN_RE
from resume_tailor.document.template_style import Bullets, Links, TemplateStyle

_DRAWINGML = "http://schemas.openxmlformats.org/drawingml/2006/main"
#: Word's own fallback when no style or default sets a size.
_WORD_DEFAULT_PT = 10.0


class Margins(BaseModel):
    """Page margins in inches."""

    top: float = Field(ge=0, le=3)
    bottom: float = Field(ge=0, le=3)
    left: float = Field(ge=0, le=3)
    right: float = Field(ge=0, le=3)


class FieldStyle(BaseModel):
    """One «field»'s emphasis. `None` leaves that property as the template has it."""

    label: str
    bold: bool | None = None
    italic: bool | None = None
    underline: bool | None = None


class SeparatorChoices(BaseModel):
    """One value per panel row (`adjust_separators.ROWS`); `None` leaves a row alone."""

    contact: str | None = None
    project_tech: str | None = None
    tech_items: str | None = None
    project_link: str | None = None
    skills_items: str | None = None
    coursework: str | None = None
    dates: str | None = None

    @field_validator("contact", "project_tech")
    @classmethod
    def _literal(cls, value: str | None) -> str | None:
        return None if value is None else template_style._check_separator(value)

    def chosen(self) -> dict[str, str]:
        return {k: v for k, v in self.model_dump().items() if v is not None}


class Adjustments(BaseModel):
    margins: Margins | None = None
    #: Every run's font family (headings included, so the page stays one typeface).
    font_family: str | None = Field(default=None, max_length=64)
    #: The body text size in points; every other size moves by the same amount, so
    #: headings and the name stay as much larger as they were.
    font_size: float | None = Field(default=None, ge=6, le=20)
    fields: list[FieldStyle] = Field(default_factory=list)
    separators: SeparatorChoices | None = None
    bullets: Bullets | None = None
    links: Links | None = None


class FieldState(BaseModel):
    label: str
    bold: bool
    italic: bool
    underline: bool


class CurrentLayout(BaseModel):
    """What the adjustments form starts from."""

    margins: Margins
    #: The body font (what bullets are set in); changing it replaces only this font.
    font_family: str
    font_size: float
    #: Other fonts the template's text uses (a name or headings font, say), which a
    #: font change leaves alone.
    other_fonts: list[str] = Field(default_factory=list)
    fields: list[FieldState]
    #: Each separator row the template prints, with its current value.
    separators: dict[str, str] = Field(default_factory=dict)
    bullets: Bullets = Field(default_factory=Bullets)
    #: None when the template prints no links.
    links: Links | None = None


def _runs(doc):
    for paragraph, _loc in docx_text.iter_document_paragraphs(doc):
        yield from paragraph.runs


def _style_chain_value(style, getter):
    while style is not None:
        value = getter(style.font)
        if value is not None:
            return value
        style = style.base_style
    return None


def _defaults_rpr(doc):
    styles = doc.styles.element
    return styles.find(f"{qn('w:docDefaults')}/{qn('w:rPrDefault')}/{qn('w:rPr')}")


def _default_size(doc) -> float:
    rpr = _defaults_rpr(doc)
    sz = rpr.find(qn("w:sz")) if rpr is not None else None
    if sz is not None:
        return int(sz.get(qn("w:val"))) / 2
    return _WORD_DEFAULT_PT


def _theme_font(doc, which: str) -> str | None:
    """The theme's major/minor Latin typeface (`asciiTheme="minorHAnsi"` points here)."""
    kind = "major" if which.startswith("major") else "minor"
    for rel in doc.part.rels.values():
        if rel.reltype.endswith("/theme"):
            root = etree.fromstring(rel.target_part.blob)
            latin = root.find(f".//{{{_DRAWINGML}}}{kind}Font/{{{_DRAWINGML}}}latin")
            if latin is not None and latin.get("typeface"):
                return latin.get("typeface")
    return None


def _rfonts_family(rpr, doc) -> str | None:
    fonts = rpr.find(qn("w:rFonts")) if rpr is not None else None
    if fonts is None:
        return None
    theme = fonts.get(qn("w:asciiTheme")) or fonts.get(qn("w:hAnsiTheme"))
    if theme:
        return _theme_font(doc, theme)
    return fonts.get(qn("w:ascii")) or fonts.get(qn("w:hAnsi"))


def _default_family(doc) -> str:
    return _rfonts_family(_defaults_rpr(doc), doc) or "Calibri"


def _size(run, doc) -> float:
    if run.font.size is not None:
        return run.font.size.pt
    for style in (run.style, run._parent.style if hasattr(run._parent, "style") else None):
        found = _style_chain_value(style, lambda f: f.size)
        if found is not None:
            return found.pt
    return _default_size(doc)


def _family(run, doc) -> str:
    found = _rfonts_family(run._r.rPr, doc)
    styles = (run.style, run._parent.style if hasattr(run._parent, "style") else None)
    for style in styles:
        while found is None and style is not None:
            found = _rfonts_family(style.element.rPr, doc)
            style = style.base_style
    return found or _default_family(doc)


def _flag(run, attr: str) -> bool:
    value = getattr(run.font, attr)
    if value is None:
        style = run._parent.style if hasattr(run._parent, "style") else None
        value = _style_chain_value(style, lambda f: getattr(f, attr))
    return bool(value)


def _token_runs(doc) -> dict[str, list]:
    """Runs holding each «field», keyed by its label as it reads in the document."""
    found: dict[str, list] = {}
    for run in _runs(doc):
        for match in TOKEN_RE.finditer(run.text):
            name = " ".join((match.group(1) or match.group(2)).split())
            if skeleton_tokens.lookup(name) is not None:
                found.setdefault(name, []).append(run)
    return found


def _body_runs(doc, tokens: dict[str, list]) -> list:
    """The runs that count as body text: bullets first, else every field run."""
    bullets = [r for label, runs in tokens.items() if label.endswith("bullet") for r in runs]
    return bullets or [r for runs in tokens.values() for r in runs] or list(_runs(doc))


#: Symbol fonts set on a hand-typed marker or icon: not a "font the text uses".
_SYMBOL_FONT_WORDS = ("symbol", "wingdings", "webdings", "dingbat")


def _body_family(doc, tokens: dict[str, list]) -> str:
    families = [_family(r, doc) for r in _body_runs(doc, tokens)]
    return max(set(families), key=families.count) if families else _default_family(doc)


def _other_families(doc, body: str) -> list[str]:
    """Fonts that set visible text, other than `body`, in first-seen order."""
    seen: dict[str, str] = {}
    for run in _runs(doc):
        if not run.text.strip():
            continue
        family = _family(run, doc)
        key = family.casefold()
        if key == body.casefold() or any(w in key for w in _SYMBOL_FONT_WORDS):
            continue
        seen.setdefault(key, family)
    return list(seen.values())


def _mark_family(paragraph, rpr, doc) -> str:
    found = _rfonts_family(rpr, doc)
    style = paragraph.style
    while found is None and style is not None:
        found = _rfonts_family(style.element.rPr, doc)
        style = style.base_style
    return found or _default_family(doc)


def current(
    raw: bytes,
    style: TemplateStyle = template_style.DEFAULT,
    date_separator: str = " - ",
) -> CurrentLayout:
    doc = docx.Document(io.BytesIO(raw))
    section = doc.sections[0]
    tokens = _token_runs(doc)
    body = _body_runs(doc, tokens)
    sizes = [_size(r, doc) for r in body]
    family = _body_family(doc, tokens)
    fields = [
        FieldState(
            label=label,
            bold=_flag(runs[0], "bold"),
            italic=_flag(runs[0], "italic"),
            underline=_flag(runs[0], "underline"),
        )
        for label, runs in tokens.items()
    ]
    return CurrentLayout(
        margins=Margins(
            top=round(section.top_margin.inches, 2),
            bottom=round(section.bottom_margin.inches, 2),
            left=round(section.left_margin.inches, 2),
            right=round(section.right_margin.inches, 2),
        ),
        font_family=family,
        other_fonts=_other_families(doc, family),
        font_size=max(set(sizes), key=sizes.count) if sizes else _default_size(doc),
        fields=fields,
        separators=adjust_separators.current(doc, style, date_separator),
        bullets=style.bullets,
        links=style.links if _prints_links(tokens) else None,
    )


def _prints_links(tokens: dict[str, list]) -> bool:
    return any(label in tokens for label in ("LinkedIn", "GitHub", "Project"))


def styled(style: TemplateStyle, adj: Adjustments) -> TemplateStyle:
    """`style` with the adjustments that live outside the document."""
    if adj.separators is not None:
        style = adjust_separators.styled(style, adj.separators.chosen())
    update = {k: v for k, v in (("bullets", adj.bullets), ("links", adj.links)) if v}
    return style.model_copy(update=update) if update else style


def _set_family(rpr, family: str) -> None:
    """Point an `rPr` at `family` for every script, dropping theme fonts that win over it."""
    fonts = rpr.get_or_add_rFonts()
    for attr in ("asciiTheme", "hAnsiTheme", "eastAsiaTheme", "cstheme"):
        fonts.attrib.pop(qn(f"w:{attr}"), None)
    for attr in ("ascii", "hAnsi", "eastAsia", "cs"):
        fonts.set(qn(f"w:{attr}"), family)


def _paragraph_marks(doc):
    """Each paragraph with its mark's `rPr` (created where missing, ahead of `sectPr`)."""
    for paragraph, _loc in docx_text.iter_document_paragraphs(doc):
        ppr = paragraph._p.get_or_add_pPr()
        rpr = ppr.find(qn("w:rPr"))
        if rpr is None:
            rpr = OxmlElement("w:rPr")
            later = ppr.find(qn("w:sectPr"))
            if later is None:
                later = ppr.find(qn("w:pPrChange"))
            if later is not None:
                later.addprevious(rpr)
            else:
                ppr.append(rpr)
        yield paragraph, rpr


def apply(raw: bytes, adj: Adjustments) -> bytes:
    """`raw` (a layout file) with `adj` applied."""
    doc = docx.Document(io.BytesIO(raw))
    if adj.margins is not None:
        for section in doc.sections:
            section.top_margin = Inches(adj.margins.top)
            section.bottom_margin = Inches(adj.margins.bottom)
            section.left_margin = Inches(adj.margins.left)
            section.right_margin = Inches(adj.margins.right)
    tokens = _token_runs(doc)
    # Read before any write: which runs and marks are in the body font decides what a
    # font change touches (a second font, for the name or headings, keeps its own).
    body_family = _body_family(doc, tokens).casefold()
    in_body = [r for r in _runs(doc) if _family(r, doc).casefold() == body_family]
    marks_in_body = [
        rpr
        for paragraph, rpr in _paragraph_marks(doc)
        if _mark_family(paragraph, rpr, doc).casefold() == body_family
    ]
    if adj.font_size is not None:
        body = [_size(r, doc) for r in _body_runs(doc, tokens)]
        delta = adj.font_size - max(set(body), key=body.count) if body else 0
        if delta:
            # Read every size before writing any: a run's size can come from its style.
            runs = [(run, _size(run, doc)) for run in _runs(doc)]
            marks = []
            for paragraph, rpr in _paragraph_marks(doc):
                sz = rpr.find(qn("w:sz"))
                base = int(sz.get(qn("w:val"))) / 2 if sz is not None else None
                if base is None:
                    base = _style_chain_value(paragraph.style, lambda f: f.size)
                    base = base.pt if base is not None else _default_size(doc)
                marks.append((rpr, base))
            for run, size in runs:
                run.font.size = Pt(max(4.0, size + delta))
            for rpr, size in marks:
                rpr.sz_val = Pt(max(4.0, size + delta))
    if adj.font_family:
        for run in in_body:
            _set_family(run._r.get_or_add_rPr(), adj.font_family)
        for rpr in marks_in_body:
            _set_family(rpr, adj.font_family)
    if adj.separators is not None:
        adjust_separators.apply(doc, adj.separators.chosen())
    for style in adj.fields:
        for run in tokens.get(style.label, []):
            for attr in ("bold", "italic", "underline"):
                value = getattr(style, attr)
                if value is not None:
                    setattr(run.font, attr, value)
    buffer = io.BytesIO()
    doc.save(buffer)
    return buffer.getvalue()
