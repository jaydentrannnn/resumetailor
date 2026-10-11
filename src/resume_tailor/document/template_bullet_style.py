"""The bullet marker Quick adjustments chose (`TemplateStyle.bullets`), applied at build.

A choice can't live in the layout file: `retarget_bullet` puts a list back on every
bullet prototype and `normalize_bullet_numbering` re-pins the marker font. So the build
applies it last, on the tagged prototypes. Two groups: every list (job, project,
education-detail, list-section bullets, which share one list) and skills lines (their
own list, or none). Each group's paragraphs move onto a copy of their list with the new
lvl0 marker, so a list some other paragraph uses is never changed.

"None" keeps the paragraphs on a list whose marker is empty: the hanging indent still
lines the text up where the bullet's text was (indented), or the paragraph drops its
indent and the marker its tab (flush). A later glyph choice then only swaps the marker.
No LLM.
"""

from __future__ import annotations

import copy

from docx.oxml import parse_xml
from docx.oxml.ns import nsdecls, qn

from . import docx_text, template_bullets, template_tags, template_xml
from .template_style import Bullets

_LIST_TAGS = (template_tags.BULLET_TAG, template_tags.LIST_ITEM_TAG,
              template_tags.EDUCATION_DETAIL_TAG, template_tags.EDUCATION_DEGREE_TAG)  # fmt: skip
_SKILLS_TAGS = (template_tags.SKILLS_LABEL_TAG, template_tags.SKILLS_BODY_TAG)
#: Text-sized glyphs every body font draws: the marker uses the paragraph's own font.
_TEXT_GLYPHS = frozenset("•–›")
_AFTER_LVL_TEXT = {qn(t) for t in ("w:lvlPicBulletId", "w:legacy", "w:lvlJc", "w:pPr", "w:rPr")}
_NEW_LIST = (
    '<w:abstractNum {ns} w:abstractNumId="{id}"><w:multiLevelType w:val="singleLevel"/>'
    '<w:lvl w:ilvl="0"><w:start w:val="1"/><w:numFmt w:val="bullet"/>'
    '<w:lvlText w:val=""/><w:lvlJc w:val="left"/>'
    '<w:pPr><w:ind w:left="360" w:hanging="360"/></w:pPr></w:lvl></w:abstractNum>'
)


def _num_id(paragraph) -> str | None:
    return template_bullets._paragraph_num_id(paragraph)


def _lvl0(root, num_id: str | None):
    abstract = template_bullets._num_to_abstract(root).get(num_id or "")
    for anum in root.findall(qn("w:abstractNum")):
        if anum.get(qn("w:abstractNumId")) == abstract:
            return next((lvl for lvl in anum.findall(qn("w:lvl"))
                         if lvl.get(qn("w:ilvl")) == "0"), None)  # fmt: skip
    return None


def _set_marker(lvl, text: str, flush: bool) -> None:
    """lvl0 draws `text` (empty for none); a flush none also drops the marker's tab."""
    fmt = lvl.find(qn("w:numFmt"))
    if fmt is not None:
        fmt.set(qn("w:val"), "bullet")
    lvl_text = lvl.find(qn("w:lvlText"))
    if lvl_text is None:
        lvl_text = parse_xml(f"<w:lvlText {nsdecls('w')}/>")
        # Schema order: lvlText sits before the bullet picture, jc, pPr and rPr.
        later = next((el for el in lvl if el.tag in _AFTER_LVL_TEXT), None)
        if later is not None:
            later.addprevious(lvl_text)
        else:
            lvl.append(lvl_text)
    lvl_text.set(qn("w:val"), text)
    suff = lvl.find(qn("w:suff"))
    if flush and suff is None:
        lvl_text.addprevious(parse_xml(f'<w:suff {nsdecls("w")} w:val="nothing"/>'))
    elif not flush and suff is not None:
        lvl.remove(suff)
    rpr = lvl.find(qn("w:rPr"))
    if rpr is not None and text in _TEXT_GLYPHS:
        for fonts in rpr.findall(qn("w:rFonts")):
            rpr.remove(fonts)


def _list_for(doc, source: str | None, text: str, flush: bool, made: dict) -> str:
    """A list instance drawing `text`, copied from `source` (made once per source)."""
    key = (source, text, flush)
    if key in made:
        return made[key]
    numbering = doc.part.numbering_part.element
    abstracts = numbering.findall(qn("w:abstractNum"))
    new_id = str(max((int(a.get(qn("w:abstractNumId"))) for a in abstracts), default=-1) + 1)
    lvl = _lvl0(numbering, source)
    if lvl is not None:
        anum = copy.deepcopy(lvl.getparent())
        anum.set(qn("w:abstractNumId"), new_id)
        for tag in ("w:nsid", "w:tmpl", "w:numStyleLink", "w:styleLink"):
            for el in anum.findall(qn(tag)):
                anum.remove(el)
    else:
        anum = parse_xml(_NEW_LIST.format(ns=nsdecls("w"), id=new_id))
    if abstracts:
        abstracts[-1].addnext(anum)
    else:
        numbering.insert(0, anum)
    _set_marker(_lvl0_of(anum), text, flush)
    made[key] = str(numbering.add_num(int(new_id)).numId)
    return made[key]


def _lvl0_of(anum):
    return next(lvl for lvl in anum.findall(qn("w:lvl")) if lvl.get(qn("w:ilvl")) == "0")


def _ind(paragraph):
    ppr = paragraph._p.get_or_add_pPr()
    ind = ppr.find(qn("w:ind"))
    return ppr, ind


def _is_flush(ind) -> bool:
    return ind.get(qn("w:left")) == "0" and ind.get(qn("w:hanging")) in (None, "0")


def _flush_indent(paragraph) -> None:
    ppr, ind = _ind(paragraph)
    if ind is None:
        ind = parse_xml(f"<w:ind {nsdecls('w')}/>")
        ppr.append(ind)
    for attr in list(ind.attrib):
        del ind.attrib[attr]
    ind.set(qn("w:left"), "0")
    ind.set(qn("w:hanging"), "0")


def _mark_size(doc, paragraph, text: str) -> None:
    """The paragraph mark sizes the marker: shrunk for a large disc or square (as the
    build always did), the text's own size for anything else."""
    if text in template_bullets._SHRINKABLE_MARKERS:
        template_bullets.shrink_bullet_marker(doc, paragraph)
        return
    rpr = paragraph._p.get_or_add_pPr().find(qn("w:rPr"))
    if rpr is None:
        return
    body = template_bullets._body_run_size(paragraph)
    for tag in ("w:sz", "w:szCs"):
        el = rpr.find(qn(tag))
        if el is None:
            continue
        if body:
            el.set(qn("w:val"), str(body))
        else:
            rpr.remove(el)


def _apply(doc, paragraphs, choice: str, fallback: str | None, sample_ind, made) -> None:
    if choice == "keep":
        return
    flush = choice == "none_flush"
    text = "" if choice.startswith("none") else choice
    for paragraph in paragraphs:
        own = _num_id(paragraph)
        was_list = own not in (None, "0")
        if not was_list and text == "":
            continue  # "none" on a line that has no marker already reads that way
        source = own if was_list else fallback
        template_xml.set_num_id(
            paragraph, _list_for(doc, source, text, flush, made)
        )
        _ppr, ind = _ind(paragraph)
        if flush:
            _flush_indent(paragraph)
        elif not was_list or (ind is not None and _is_flush(ind)):
            # A line gaining a marker (or leaving a flush none) takes the template's
            # bullet indent, so its text lines up with the other lists'.
            if ind is not None:
                ind.getparent().remove(ind)
            if sample_ind is not None:
                _ind(paragraph)[0].append(copy.deepcopy(sample_ind))
        if text:
            _mark_size(doc, paragraph, text)


def apply_bullet_style(doc, bullets: Bullets) -> None:
    """Apply `bullets` to the tagged list and skills paragraphs of a built template."""
    if bullets.list == "keep" and bullets.skills == "keep":
        return
    paragraphs = [p for p, _loc in docx_text.iter_document_paragraphs(doc)]

    def tagged(tags):
        return [p for p in paragraphs if any(tag in p.text for tag in tags)]

    lists = [p for p in tagged(_LIST_TAGS) if _num_id(p) is not None]
    skills = tagged((template_tags.SKILLS_LABEL_TAG,)) + [
        p for p in tagged((template_tags.SKILLS_BODY_TAG,))
        if template_tags.SKILLS_LABEL_TAG not in p.text and _num_id(p) not in (None, "0")
    ]
    sample = next((p for p in lists if _num_id(p) != "0"), None)
    fallback = _num_id(sample) if sample is not None else None
    sample_ind = copy.deepcopy(_ind(sample)[1]) if sample is not None else None
    if sample_ind is not None and _is_flush(sample_ind):
        sample_ind = None  # every list is flush: the list's own indent is the bullet one
    made: dict = {}
    _apply(doc, lists, bullets.list, fallback, sample_ind, made)
    _apply(doc, skills, bullets.skills, fallback, sample_ind, made)
