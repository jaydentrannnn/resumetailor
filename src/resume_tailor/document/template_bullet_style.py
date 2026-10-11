"""The bullet marker Quick adjustments chose (`TemplateStyle.bullets`), applied at build.

A choice can't live in the layout file: `retarget_bullet` puts a list back on every
bullet prototype and `normalize_bullet_numbering` re-pins the marker font. So the build
applies it last, on the tagged prototypes. Two groups: every list (job, project,
education-detail, list-section bullets, which share one list) and skills lines (their
own list, or none). Each group's paragraphs move onto a copy of their list with the new
lvl0 marker, so a list some other paragraph uses is never changed.

"None" keeps the paragraphs on a list whose marker is empty and has no tab, and sets the
paragraph's indent so the text starts where the bullet's text did (indented) or at the
margin (flush). That list's lvl0 keeps the bullet indent, so a later glyph choice puts
the paragraph back exactly as it was. No LLM.
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


def _set_marker(lvl, text: str) -> None:
    """lvl0 draws `text`; an empty marker (none) also drops the marker's tab."""
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
    if not text and suff is None:
        lvl_text.addprevious(parse_xml(f'<w:suff {nsdecls("w")} w:val="nothing"/>'))
    elif text and suff is not None:
        lvl.remove(suff)
    rpr = lvl.find(qn("w:rPr"))
    if rpr is not None and text in _TEXT_GLYPHS:
        for fonts in rpr.findall(qn("w:rFonts")):
            rpr.remove(fonts)


def _list_for(doc, source: str | None, text: str, made: dict, bullet_ind) -> str:
    """A list instance drawing `text`, copied from `source` (made once per source). A
    none list keeps `bullet_ind` on its lvl0, for a later glyph to restore."""
    key = (source, text)
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
    lvl = _lvl0_of(anum)
    _set_marker(lvl, text)
    if not text and bullet_ind is not None:
        ppr = lvl.find(qn("w:pPr"))
        if ppr is None:
            ppr = parse_xml(f"<w:pPr {nsdecls('w')}/>")
            rpr = lvl.find(qn("w:rPr"))
            if rpr is not None:
                rpr.addprevious(ppr)
            else:
                lvl.append(ppr)
        for old in ppr.findall(qn("w:ind")):
            ppr.remove(old)
        ppr.append(copy.deepcopy(bullet_ind))
    made[key] = str(numbering.add_num(int(new_id)).numId)
    return made[key]


def _lvl0_of(anum):
    return next(lvl for lvl in anum.findall(qn("w:lvl")) if lvl.get(qn("w:ilvl")) == "0")


def _ind(paragraph):
    ppr = paragraph._p.get_or_add_pPr()
    ind = ppr.find(qn("w:ind"))
    return ppr, ind


#: `w:pPr` children that follow `w:ind` (schema order).
_AFTER_IND = {qn(t) for t in ("w:contextualSpacing", "w:mirrorIndents", "w:suppressOverlap",
              "w:jc", "w:textDirection", "w:textAlignment", "w:textboxTightWrap",
              "w:outlineLvl", "w:divId", "w:cnfStyle", "w:rPr", "w:sectPr", "w:pPrChange")}  # fmt: skip


def _set_ind(paragraph, ind) -> None:
    """Replace the paragraph's own indent with `ind` (None: inherit the list's)."""
    ppr, old = _ind(paragraph)
    if old is not None:
        ppr.remove(old)
    if ind is None:
        return
    later = next((el for el in ppr if el.tag in _AFTER_IND), None)
    if later is not None:
        later.addprevious(ind)
    else:
        ppr.append(ind)


def _marker_text(lvl) -> str | None:
    el = lvl.find(qn("w:lvlText")) if lvl is not None else None
    return None if el is None else el.get(qn("w:val"))


def _bullet_ind(doc, paragraph):
    """The indent `paragraph` has as a bullet: kept on its list when the marker is none,
    else its own, else its list's."""
    lvl = _lvl0(doc.part.numbering_part.element, _num_id(paragraph))
    listed = lvl.find(f"{qn('w:pPr')}/{qn('w:ind')}") if lvl is not None else None
    own = _ind(paragraph)[1]
    found = listed if _marker_text(lvl) == "" or own is None else own
    return copy.deepcopy(found) if found is not None else None


def _twips(ind, attr: str) -> int:
    try:
        return int(ind.get(qn(f"w:{attr}")) or 0) if ind is not None else 0
    except ValueError:
        return 0


def _text_start(ind) -> int:
    """Where a bullet's text starts: the left indent under a hanging indent, else the
    default tab stop after the marker."""
    left = _twips(ind, "left") or _twips(ind, "start")
    if _twips(ind, "hanging") > 0:
        return left
    return ((left + _twips(ind, "firstLine")) // 720 + 1) * 720


def _plain_ind(left: int):
    return parse_xml(f'<w:ind {nsdecls("w")} w:left="{left}" w:hanging="0"/>')


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
    text = "" if choice.startswith("none") else choice
    for paragraph in paragraphs:
        own = _num_id(paragraph)
        was_list = own not in (None, "0")
        if not was_list and not text:
            continue  # "none" on a line that has no marker already reads that way
        # A line gaining a marker takes the lists' bullet indent, so its text lines up.
        bullet_ind = _bullet_ind(doc, paragraph) if was_list else copy.deepcopy(sample_ind)
        source = own if was_list else fallback
        template_xml.set_num_id(paragraph, _list_for(doc, source, text, made, bullet_ind))
        if text:
            _set_ind(paragraph, bullet_ind)
            _mark_size(doc, paragraph, text)
        elif choice == "none_flush":
            _set_ind(paragraph, _plain_ind(0))
        else:
            _set_ind(paragraph, _plain_ind(_text_start(bullet_ind)))


def apply_bullet_style(doc, bullets: Bullets) -> None:
    """Apply `bullets` to the tagged list and skills paragraphs of a built template."""
    if bullets.list == "keep" and bullets.skills == "keep":
        return
    paragraphs = [p for p, _loc in docx_text.iter_document_paragraphs(doc)]

    def tagged(tags):
        return [p for p in paragraphs if any(tag in p.text for tag in tags)]

    lists = [p for p in tagged(_LIST_TAGS) if _num_id(p) not in (None, "0")]
    skills = tagged((template_tags.SKILLS_LABEL_TAG,)) + [
        p for p in tagged((template_tags.SKILLS_BODY_TAG,))
        if template_tags.SKILLS_LABEL_TAG not in p.text and _num_id(p) not in (None, "0")
    ]
    sample = lists[0] if lists else None
    fallback = _num_id(sample) if sample is not None else None
    sample_ind = _bullet_ind(doc, sample) if sample is not None else None
    made: dict = {}
    _apply(doc, lists, bullets.list, fallback, sample_ind, made)
    _apply(doc, skills, bullets.skills, fallback, sample_ind, made)
