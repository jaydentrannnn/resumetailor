"""Deterministic facts for education, skill checklists and routine notices."""

from __future__ import annotations

import contextlib
import re
from collections.abc import Iterable, Iterator
from contextvars import ContextVar

HIGH_SCHOOL = "high_school_graduation_year"
SKILLS = "programming_languages"
ACKNOWLEDGEMENT = "routine_acknowledgement"
TALENT_POOL = "talent_pool_consent"
TYPED_CONSENT = "typed_consent"
PROTECTED_KEYS = frozenset({
    HIGH_SCHOOL, SKILLS, ACKNOWLEDGEMENT, TALENT_POOL, TYPED_CONSENT, "relatives_at_company",
    "consider_other_positions", "minimum_qualifications", "advertising_consent",
    "experience_years", "recent_graduate_or_student",
})

#: Consent to keep the applicant's data for OTHER openings (a talent pool), as opposed to
#: processing it for this application. The applicant declines these (2026-10-12).
_TALENT_POOL = re.compile(
    r"(?:consent|agree|permission|allow|may we|keep|retain|store).{0,160}"
    r"(?:(?:other|future|additional|similar)\s+(?:job|career|employment|work)?\s*"
    r"(?:opportunit|opening|position|role|vacanc)|talent (?:pool|community|network))",
    re.S,
)


def talent_pool(text: str) -> bool:
    """A question asking to keep the applicant's data for other job opportunities."""
    return bool(_TALENT_POOL.search(text.casefold()))


#: A notice, consent or declaration the applicant is asked to accept.
_NOTICE = re.compile(
    r"acknowledg|confirm|\bi agree\b|\bagree (?:to|with) (?:the|these|this|our|all|its)\b"
    r"|understand and (?:agree|accept|acknowledge)|\bconsent|privacy|personal information policy"
    r"|read.{0,35}(?:statement|notice|policy)|certif|attest|signature"
    r"|terms (?:and|&) conditions|\bi authori[sz]e\b|\bdeclar(?:e|ation)\b"
    r"|\bi\s+(?:fully\s+|also\s+)?understand\b|\bi\s+have\s+read\b"
    r"|electronic(?:ally)?\s+sign|background\s+(?:check|screen)|drug\s+(?:screen|test)"
    r"|\b(?:i|you)\s+(?:also\s+|hereby\s+)?(?:accept|agree|consent)\b|e-?verify"
    r"|\bby\s+(?:checking|ticking|selecting|clicking)\b|arbitration|code\s+of\s+conduct"
    r"|drug[- ]free|at[- ]will"
    r"|\bi\s+(?:have\s+been|was|am|'m)\s+(?:informed|advised|notified|made\s+aware|aware)\b"
)
#: A declaration that states a fact about the applicant ("I confirm that I am legally
#: authorized to work..."): answered from that fact, never agreed to blindly.
_FACT_CLAIM = re.compile(
    r"\b(?:i|you)\s+(?:am|are|'m|'re|was|were|hold|possess|do\s+not|don'?t"
    r"|have\s+(?!read|reviewed|answered|understood|carefully|provided|completed this)"
    r"|(?:will\s+(?:not\s+)?|currently\s+)?(?:require|need))\b"
    r".{0,120}?(?:authori[sz]ed\s+to\s+work|citizen|permanent\s+resident|green\s+card"
    r"|sponsor|\bvisa\b|non[- ]?compet|non[- ]?solicit|convict|felon|criminal|\b18\b"
    r"|years\s+of\s+age|clearance)"
)
#: Optional opt-ins the applicant declines (marketing, alerts, texts, talent pools, news
#: about other openings). "Other positions" is a preference instead (`questions`).
_OPT_IN = re.compile(
    r"marketing|newsletter|promotional|job\s+(?:alerts?|notifications?|recommendations?)"
    r"|text\s+messag|\bsms\b|whatsapp|talent (?:community|network|pool)|advertising partners?"
    r"|share.{0,70}personal information.{0,70}partners|\bnews\b|hiring\s+events?"
    r"|event\s+invitations?|updates\s+about\s+(?:new\s+)?(?:openings|jobs|roles|opportunit)"
    r"|(?:future|other|new|additional|similar|upcoming|suitable|relevant|matching|open)\s+"
    r"(?:job\s+|career\s+|employment\s+|recruit\w*\s+)?"
    r"(?:opportunit|openings?\b|roles?\b|vacanc|jobs?\b|campaigns?\b|postings?\b)"
    r"|(?:jobs?|roles?|positions?|opportunit\w*|openings?)\s+(?:that\s+)?match"
    # Contact about other positions; "consider me for other positions" is a preference.
    r"|\b(?:about|regarding|of)\s+(?:other|future|new|additional|similar|upcoming|suitable)"
    r"\s+positions?\b"
    r"|career\s+(?:tips|stories|updates|events?|news|content|opportunit)"
    r"|recruit\w*\s+(?:events?|campaigns?)|candidate\s+database"
    r"|\b(?:keep|kept|retain|hold|store)\w*\b.{0,40}\bon\s+file\b"
    r"|mobile\s+alerts?|partner\s+companies|affiliates.{0,40}\b(?:roles|openings|positions|jobs)"
    # Surveys sent later, not the self-identification survey on this form.
    r"|\b(?:invit\w*|participat\w*|take\s+part)\b.{0,40}\bsurveys?\b"
    r"|research\s+stud|user\s+research|focus\s+groups?|hear\s+from\b"
    r"|stay\s+(?:in\s+touch|connected)|keep\s+in\s+touch|alumni|mailing\s+list"
    r"|products?\s+(?:and|&|or)\s+services|push\s+notifications?|autodial|pre-?recorded"
    r"|automated\s+(?:calls?|messages?|texts?)|visible\s+to\s+(?:other\s+)?(?:employers|recruiters)"
    r"|(?:group\s+companies|subsidiaries|clients)\b.{0,60}\brecruit"
    r"|\b(?:join|our)\s+(?:the\s+)?(?:[\w&]+\s+){0,3}(?:community|network)\b"
)
_OPT_IN_ACTION = re.compile(
    r"\b(?:i|we)\s+(?:(?:would|do)\s+)?(?:not\s+)?(?:like|want|wish|agree|consent|authori[sz]e"
    r"|allow|permit)\b"
    r"|\b(?:would|do|will)\s+you\s+(?:like|want|wish|agree|consent|allow|permit)\b"
    r"|\bmay\s+(?:we\s+)?(?:contact|send|text|email|call|keep|retain|share|reach|notify"
    r"|inform|add|pass|use\s+my)\b"
    r"|\bcan\s+(?:contact|send|text|email|call|reach)\s+me\b|\bagreement\s+to\s+receive\b"
    r"|\bopt(?:ed)?[- ]?in\b"
    r"|^\s*(?:join|subscribe|sign\s*(?:me\s+)?up|receive|send\s+me|email\s+me|text\s+me|keep\s+me"
    r"|stay\s+(?:in\s+touch|connected)|allow)\b|\binvite\s+me\b"
    r"|^\s*(?:consent|agree|permission)\s+(?:to|for)\b"
    r"|^\s*(?:sms|text messages?|marketing|newsletter|job alerts?)\s+(?:opt[- ]?in|consent)\b"
    # An opt-in worded as an acknowledgement, and an opt-out: still the applicant's choice.
    r"|\b(?:i|you)\s+(?:also\s+|hereby\s+)?(?:acknowledge|confirm|certify|understand|accept"
    r"|agree|consent)\b"
    r"|\b(?:keep|notify|inform|contact|email|text|call|add)\s+me\b|\bbeing\s+contacted\b"
    r"|\bto\s+be\s+(?:contacted|added|kept)\b|\bunsubscribe\b|\bdo\s+not\s+(?:contact|send|email"
    r"|text|call|add|share|keep)\b|\b(?:i'?d|i\s+would)\s+(?:prefer|rather)\b|\bprefer\s+not\b"
    r"|\b(?:please|we)\s+(?:will\s+)?(?:keep|retain|add)\b|\breach\s+out\b"
)

# -- one statement at a time: a notice is routine only when every statement in it is ----
_SENTENCE_BREAK = re.compile(r"(?<=[.;!?])\s+|\s+[-–—•]\s+|\s*;\s*|\.\.\.+")
#: Where a sentence holds a second statement: "and" before a new verb ("I agree to the
#: terms and would like to join..."), but not "terms and conditions".
_CLAUSE_BREAK = re.compile(
    r",?\s+(?:and|but|as\s+well\s+as|&)\s+"
    r"(?=(?:that|i|to|also|further|hereby|would|will|am|opt|confirm|certify|agree|acknowledge"
    r"|consent|understand|authori[sz]e|accept|attest|declare|receive|join|have|do|did|are|is"
    r"|can|were|hold|possess|meet|satisfy|qualify|reside|live|speak|own|require|need|plan"
    r"|intend|expect|currently|was|could|graduat\w*)\b)"
)
#: A later clause with no subject of its own continues the applicant's statement ("I
#: agree to the terms and possess a passport" says "I possess a passport").
_OWN_SUBJECT = re.compile(r"^(?:that|to|i|you|we|they|it|this|the|my|our|your)\b")
#: A statement the applicant makes: first person, an instruction to them, "you agree...".
_APPLICANT_VOICE = re.compile(
    r"(?<![\w-])(?:i|i'm|i've|me|my|mine|myself)(?![\w-])"  # not the "I-9" form
    r"|^(?:please\s+)?(?:acknowledge|confirm|agree|accept|certify|attest|consent|authori[sz]e"
    r"|declare|read|review|check|select|tick|indicate|sign)\b"
    r"|\byou\s+(?:hereby\s+)?(?:agree|consent|acknowledge|accept|certify|confirm|understand"
    r"|authori[sz]e|attest|declare)\b"
)
#: A requirement placed on the applicant ("Candidates must be authorized to work", "This
#: role is based on-site"): acknowledging it can claim the applicant meets it.
_REQUIREMENT = re.compile(
    r"\b(?:you|applicants?|candidates?|interns?|employees?)\s+(?:must|should|will\s+need\s+to"
    r"|need\s+to|are\s+required\s+to|will\s+be\s+required\s+to)\s+(?:be|have|hold|possess"
    r"|reside|live|work|relocate|commit)\b"
    r"|\b(?:role|position|job|internship|program|opportunity)\s+(?:requires?|is\s+(?:a\s+|an\s+)?"
    r"(?:located|based|on[- ]?site|in[- ]office|remote|hybrid|full[- ]time|part[- ]time))\b"
    r"|\bmust\s+be\s+(?:legally|authori|eligible|able|willing|at\s+least|currently|enrolled)"
)
_ASSENTING = (
    r"aware|electronically|signing|submitting|applying|providing|giving|consenting|agreeing"
    r"|accepting|acknowledging|confirming|certifying|attesting|authori[sz]ing|voluntarily|hereby"
)
#: A statement of fact about the applicant ("I am authorized", "I have never been
#: convicted", "you are a member of..."), unlike the verbs that accept a notice ("I am
#: aware", "I have read", "you agree", "I will be asked to complete a background check").
_STATE_CLAIM = re.compile(
    # Not a condition the notice sets ("...if I am offered a job").
    rf"(?<!\bif\s)(?<!\bwhen\s)(?<!\bonce\s)"
    rf"\b(?:i(?:'m|\s+am)|you(?:'re|\s+are))\b(?!\s+(?:{_ASSENTING})\b)"
    r"|\b(?:i|you)(?:'ve|\s+have)\b(?!\s+(?:read|reviewed|received|answered|understood|carefully"
    r"|fully|provided|submitted|given|supplied|entered|stated|made|disclosed|included"
    r"|completed\s+(?:this|the)|been\s+(?:informed|advised|given|provided|made\s+aware)"
    r"|had\s+the\s+opportunity|not\s+(?:knowingly\s+|intentionally\s+|wilfully\s+|willfully\s+)?"
    r"(?:withheld|omitted|concealed|misrepresented|falsified|left\s+out))\b)"
    r"|\b(?:i|you)\s+(?:hold|possess|meet|satisfy|qualify|could|won'?t|do\s+not|don'?t|did\s+not"
    r"|didn'?t|was|were|currently|live|reside|plan|intend|expect|graduat\w*|speak|own|require"
    r"|need|work)\b"
    r"|\bi\s+can\b(?!\s+(?:withdraw|revoke|opt|unsubscribe|request|change|update|access|ask)\b)"
    r"|\b(?:i|you)\s+will\b(?!\s+(?:be\s+)?(?:asked|required|subject|expected|redirected)\s+to\b"
    r"|\s+receive\b|\s+(?:comply|abide|adhere|cooperate|notify|inform)\b)"
    r"|\bapply\s+to\s+me\b|\bme\s+to\s+(?:be|have|hold|work|relocate)\b"
    r"|consider(?:ed)?\s+(?:me\s+)?for\s+(?:other|additional|similar)\b"
)
#: A question or request for something about the applicant ...
_QUESTION_START = re.compile(
    r"^(?:are|is|do|does|did|have|has|had|will|would|can|could|were|was|what|when|where|which"
    r"|who|how|why)\b"
    r"|^(?:please\s+)?(?:list|describe|provide|enter|tell\s+us|share|explain|specify|state"
    r"|summari[sz]e|write|outline|discuss|detail|upload|attach|elaborate|rate|rank"
    r"|give\s+(?:us\s+)?(?:an?\s+)?example)\b"
)
_QUESTION = re.compile(rf"{_QUESTION_START.pattern}|\?\W*$")
#: ... unless it asks for assent to a process ("Do you agree to the terms?", "Are you
#: comfortable with a background check?").
_ASSENT_QUESTION = re.compile(
    r"^(?:do|will|would|can)\s+you\s+(?:hereby\s+)?(?:agree|consent|accept|acknowledge"
    r"|understand|authori[sz]e|certify|attest)\b"
    r"|^(?:have|did)\s+you\s+read\b"
    r"|^(?:are|would)\s+you\s+(?:be\s+)?(?:comfortable|willing|okay|ok|able)\s+"
    r"(?:with|to\s+(?:undergo|complete|consent|submit|pass|sign))\b"
)
#: What a routine statement is about: the documents, processes and declarations agreed
#: to without asserting anything about the applicant.
_PROCESS = re.compile(
    r"\bterms\b|\bconditions\b|\bt\s*&\s*c|polic(?:y|ies)|\bnotice|privacy|statements?\b|disclosures?"
    r"|agreements?\b|provisions?\b|poster|handbook|code\s+of\s+conduct|consent\s+form"
    r"|authori[sz]ation\s+form|the\s+(?:above|following|preceding)\b|the\s+contents?\b"
    r"|(?:checkbox(?:es)?|boxes|items)\s+(?:above|below)|job\s+description"
    r"|(?:this|the|my)\s+application\b|information\b|\bdata\b|responses|truthful|accura(?:te|cy)"
    r"|\btrue\b|\bcomplete\b|\bcorrect\b|arbitration|disputes?\b|at[- ]will|e-?verify|background"
    r"|\bdrug|screen(?:ing)?\b|reference\s+checks?|verif(?:y|ication)|investigat"
    r"|electronic(?:ally)?|signature|\bsign(?:ing|ed)?\b|record(?:ed|ing)\b|automated"
    r"|contingent|\bfalse\b|omission|misrepresent|rejection|termination|dismissal"
    r"|equal\s+(?:employment\s+)?opportunity|pay\s+transparency|know\s+your\s+rights|\beeo\b"
    r"|demographic|self[- ]identification|(?:tobacco|smoke|drug|alcohol)[- ]free"
    r"|communications?\b|hiring\s+process|payment|cookies?|retention|withdraw"
    r"|\bprocessing\b|\btransfer(?:s|red)?\b|confidential|non[- ]?disclosure|candidacy"
    r"|\bapply(?:ing)?\s+for\b|withh(?:e|o)ld|omitted|conceal|\breferences?\b|\binterviews?\b"
)
#: A caption that names a field to fill ("Privacy rights experience (in years)", "Upload
#: your signed form"), not a notice: never agreed to on its process words alone.
_FIELD_CAPTION = re.compile(
    r"\bexperience\b|\byears?\b|\bnumber\b|\bname\s+of\b|\bdate\b|\baddress\b|e-?mail"
    r"|\bphone\b|password|\bupload|\battach|\burl\b|\blink\b|\blevel\b|\bscore\b|\bamount\b"
    r"|\bsalary\b|\btitle\b|\bexplain|\bdescribe|\bsignature\s+of\b|\bid\b|\bprovider\b"
    r"|\byour\s+(?!application|candidacy|data|information|personal|privacy|rights|consent)\w+"
)
#: What a caption accepts when it is not a statement of the applicant's own ("Privacy
#: Notice", "Background Check Authorization"): a named document or process, never a bare
#: field ("Applicant Signature", "Certifications", "Educational background").
_DOCUMENT = re.compile(
    r"notice|polic(?:y|ies)|\bterms\b|agreement|statement|disclosure|consent|acknowledg"
    r"|declar|authori[sz]ation|attestation|applicant\s+certification|confirmation\s+of"
    r"|certification\s+(?:of|statement|and)|conditions|provisions?\b|poster|handbook"
    r"|code\s+of\s+conduct|e-?verify|privacy|arbitration|at[- ]will|\beeo\b"
    r"|equal\s+(?:employment\s+)?opportunity|pay\s+transparency|background\s+(?:check|screen)"
    r"|drug\s+(?:test|screen)|drug[- ]free|\bi\s+(?:agree|accept|understand)|\bi\s+have\s+read"
    r"|\b(?:acme|we|our|the\s+company)\b.{0,80}\b(?:will|may|is|are|uses?|participates?"
    r"|collects?|processes|shares?|retains?)\b"
)
#: The words of a bare acceptance ("I acknowledge", "Yes, I have read and agree", "Type
#: 'I agree' to continue"): a statement made of these alone accepts what it captions.
_ASSENT_WORDS = re.compile(
    r"\b(?:i|we|you|do|hereby|have|has|fully|carefully|willingly|voluntarily|yes|ok(?:ay)?|and|or"
    r"|to|the|that|this|these|all|it|of|a|an|my|will|shall|please|by|submit(?:ting)?"
    r"|application|form|checking|selecting|ticking|clicking|check"
    r"|select|tick|click|box|checkbox|type|enter|write|continue|proceed|here|below|above"
    r"|following|acknowledg\w*|confirm\w*|agree\w*|accept\w*|consent\w*|understand|understood"
    r"|read|review(?:ed)?|certif(?:y|ied)|attest\w*|declar\w*|authori[sz]\w*|sign(?:ed)?"
    r"|comply|abide|adhere|with)\b"
)
#: Subjects that bear on the applicant's eligibility, availability or background: a
#: notice that mentions one is never routine on its wording alone.
_CLAIM_TOPIC = re.compile(
    r"authori[sz]ed\s+to\s+work|work\s+authori[sz]ation|eligib\w*\s+to\s+work|citizen"
    r"|permanent\s+resident|green\s+card|sponsor|\bvisas?\b|non[- ]?compet|non[- ]?solicit"
    r"|restrictive\s+covenant|convict|felon|criminal\s+(?:record|offen[cs]e|charge)|\b18\b"
    r"|years\s+of\s+age|legal\s+age|clearance|relocat|on[- ]?site|in[- ]office|\bhybrid\b"
    r"|\bremote\b|commut|hours?\s*(?:per|a|/)\s*week|full[- ]time|part[- ]time|\bshifts?\b"
    r"|weekends?|\btravel|start\s+date|available\s+to\s+(?:work|start)|availability|graduat"
    r"|enrol|\bdegree\b|\bgpa\b|grade\s+point|coursework|licen[cs]ed|licensure"
    r"|driver'?s?\s+licen|(?:professional|valid|active)\s+licen|certified|certifications\b"
    r"|professional\s+certification"
    r"|fluen|proficien|\bqualifications?\b|relatives?\b|family\s+members?|related\s+to"
    r"|government\s+(?:employee|official)|former\s+employee|previously\s+(?:worked|employed)"
    r"|currently\s+employed|(?:years?|work|professional|relevant|prior|previous)\s+(?:of\s+)?"
    r"experience|experience\s+(?:with|in)\b|\bskills?\b"
)


def _strip(part: str) -> str:
    return part.strip(" *:,-–—\"'“”")


def _statements(low: str, *, asks: bool = True) -> list[tuple[str, bool]]:
    """Each clause in ``low``, with whether it is a question put to the applicant (only
    when ``asks``: help text's "Questions? Contact us" is not). A question's later
    clauses are questions of their own only when worded as one ("..., and are you...")."""
    out = []
    for sentence in filter(None, map(_strip, _SENTENCE_BREAK.split(low))):
        asked = asks and bool(_QUESTION.search(sentence))
        clauses = list(filter(None, map(_strip, _CLAUSE_BREAK.split(sentence))))
        voiced = bool(clauses) and bool(_APPLICANT_VOICE.search(clauses[0]))
        for index, clause in enumerate(clauses):
            question = asked and (index == 0 or bool(_QUESTION_START.search(clause)))
            if index and voiced and not question and not _OWN_SUBJECT.search(clause):
                verb = re.sub(r"^(?:also|further)\s+", "", clause)
                clause = "i " + re.sub(r"^are\b", "am", re.sub(r"^were\b", "was", verb))
            out.append((clause, question))
    return out


def _claims(statement: str, question: bool) -> bool:
    """Whether ``statement`` asserts or asks something about the applicant."""
    if question and not _ASSENT_QUESTION.search(statement):
        return True
    return bool(_STATE_CLAIM.search(statement))


def asks(text: str) -> bool:
    """Whether ``text`` puts a question to the applicant anywhere."""
    return any(question for _part, question in _statements(text.casefold()))


def first_person_claim(text: str) -> bool:
    """Whether ``text`` states something about the applicant in their own words ("I am
    not authorized to work...", "I do not require sponsorship"), not as a question."""
    return any(not question and _STATE_CLAIM.search(part)
               for part, question in _statements(text.casefold()))


def _process(statement: str) -> bool:
    bare = not re.sub(r"[\W\d_]+", " ", _ASSENT_WORDS.sub(" ", statement)).strip()
    return bare or bool(_PROCESS.search(statement))


#: A text box the applicant fills to accept a notice: an e-signature, today's date beside
#: it, or a word the instruction quotes ("Type 'I agree' to continue").
_TYPE_TOKEN = re.compile(
    r"\b(?:type|enter|write|select|choose|(?:answer|respond|reply)(?:\s+with)?)\s+"
    r"(?:the\s+(?:word|phrase|text)\s+)?[\"'“‘]([^\"'”’]{1,30})[\"'”’]",
    re.I,
)
_SIGNATURE = re.compile(
    r"\be-?signature\b|\bsignature\b(?!\s*date)|electronic(?:ally)?\s+sign"
    r"|\b(?:type|enter)\s+your\s+(?:full\s+|legal\s+)*name\b.{0,40}\b(?:sign|signature|acknowledg|agree)"
)
_SIGNED_DATE = re.compile(r"^(?:today'?s\s+)?date$|signature\s+date|date\s+signed|^today'?s\s+date")


def typed_consent(text: str, help_text: str = "") -> str:
    """What to type into a consent text box: the quoted word, "full_name" for a
    signature, "today" for its date; "" when ``text`` is not such a box."""
    context = f"{text} {help_text}"
    token = _TYPE_TOKEN.search(context)
    # Only a notice's token ("Type 'I agree'"), never "Enter 'N/A' if none" or a quoted
    # word that would assert a fact about the applicant.
    if token and acknowledgement(text, help_text) == "routine":
        return token.group(1).strip()
    label = re.sub(r"[*:]\s*$", "", text.strip()).strip().casefold()
    if _SIGNED_DATE.search(label):
        return "today"
    if _SIGNATURE.search(context.casefold()):
        return "full_name"
    return ""


#: The model's reading of "unclear" notices ("routine" or "fact"), by `notice_key`, for
#: the questions being planned (`notice_verdicts`).
_VERDICTS: ContextVar[dict[str, str] | None] = ContextVar("notice_verdicts", default=None)


def notice_key(text: str, help_text: str = "") -> str:
    return " ".join(f"{text} {help_text}".split()).casefold()


@contextlib.contextmanager
def notice_verdicts(verdicts: dict[str, str]) -> Iterator[None]:
    """Read each "unclear" notice ``verdicts`` names as its verdict while active."""
    token = _VERDICTS.set(verdicts)
    try:
        yield
    finally:
        _VERDICTS.reset(token)


def acknowledgement(text: str, help_text: str = "") -> str:
    """What kind of notice ``text`` (with the ``help_text`` beside it) is, using the whole
    question, not a box's caption.

    In priority order: "optional" (any statement is an opt-in to decline), "fact" (one
    asserts or asks something about the applicant), "routine" (every statement the
    applicant makes is process language: a notice, policy, check or declaration of
    accuracy to agree to), "unclear" (a notice that is neither, which is never agreed
    to on its wording, unless the model's reading under `notice_verdicts` settles it),
    else "" (not a notice).
    """
    kind = _wording(text, help_text)
    if kind == "unclear":
        return (_VERDICTS.get() or {}).get(notice_key(text, help_text), kind)
    return "unclear" if kind == _FIELD else kind


def needs_reading(text: str, help_text: str = "") -> bool:
    """Whether the model's reading may settle this notice: an "unclear" statement, never
    a field's caption ("Confirm your password", "Applicant Signature")."""
    return _wording(text, help_text) == "unclear"


#: `_wording`'s kind for a field's caption with notice words: "unclear" to callers, and
#: never put to the model, which reads any caption as a statement to accept.
_FIELD = "field"


def _wording(text: str, help_text: str) -> str:
    low = f"{text} {help_text}".casefold()
    caption = _statements(text.casefold())
    statements = caption + _statements(help_text.casefold(), asks=False)
    if talent_pool(low) or any(
        _OPT_IN.search(part) and _OPT_IN_ACTION.search(part)
        for part in (low, *(part for part, _question in statements))
    ):
        return "optional"
    if _OPT_IN.search(low) and re.search(r"\bexperience\b|\bskills?\b|\bexpertise\b", low):
        return "fact"
    if re.search(r"graduat|date of birth|\bminimum\s+qualification", low):
        return "fact"
    if not _NOTICE.search(low):
        return ""
    voiced = [(part, question) for part, question in statements
              if question or _APPLICANT_VOICE.search(part)]
    if _FACT_CLAIM.search(low) or any(_claims(part, question) for part, question in voiced):
        return "fact"
    # Third-person context ("Acme participates in E-Verify") asserts nothing, unless it is
    # a requirement placed on the applicant; a caption with no statement of the
    # applicant's own ("Privacy Notice") must itself be process language.
    own = [part for part, _question in voiced]
    required = [part for part, _question in statements if _REQUIREMENT.search(part)]
    checked = own or [part for part, _question in caption or statements]
    field = any(_FIELD_CAPTION.search(part) for part in checked) or bool(
        own and re.search(r":[\s*]*$", text)  # "I have read about Acme in:"
    )
    if not own and (field or not _DOCUMENT.search(" ".join(checked))):
        return _FIELD
    process = all(_process(part) for part in checked)
    if field and not process:
        return _FIELD
    if any(_CLAIM_TOPIC.search(part) for part in checked + required) or not process:
        return "unclear"
    return "routine"


def semantic_key(text: str, help_text: str = "") -> str:
    low = text.casefold()
    if re.search(r"\bhigh school\b|\bsecondary school\b", low) and re.search(
        r"graduat|complet|finish", low
    ):
        return HIGH_SCHOOL
    if re.search(r"\bprogramming languages?\b", low):
        return SKILLS
    if re.search(r"\b(?:current )?grade level\b", low) or (
        re.search(r"\byear\b.{0,25}\bin\s+(?:school|college|university)\b", low)
        and not re.search(r"\bstart|\bbegin|\benter|graduat", low)
    ):
        return "class_year"
    # "Are you related to a current Workday employee?" too; ties to a customer, supplier,
    # competitor or official are a conflict of interest instead (`ats_hints`).
    if (
        re.search(r"\brelatives?\b|\bfamily members?\b|\brelated to\b", low)
        and re.search(r"work|employ|company|management committee", low)
        and not re.search(
            r"\bcompetitor|\bother compan|\bcustomer|\bsupplier|\bvendor|\bofficial"
            r"|conflict of interest",
            low,
        )
    ):
        return "relatives_at_company"
    if talent_pool(text):
        return TALENT_POOL
    if acknowledgement(text, help_text):
        return ACKNOWLEDGEMENT
    return ""


def year_option(options: Iterable[str], year: str) -> str | None:
    if not re.fullmatch(r"\d{4}", year):
        return None
    wanted = int(year)
    hits = []
    for option in options:
        years = [int(x) for x in re.findall(r"\b\d{4}\b", option)]
        if not years:
            continue
        low = option.casefold()
        if len(years) == 2:
            matches = years[0] <= wanted <= years[1]
        elif re.search(r"or (?:earlier|before)|and (?:earlier|before)", low):
            matches = wanted <= years[0]
        elif re.search(r"or (?:later|after)|and (?:later|after)", low):
            matches = wanted >= years[0]
        elif "before" in low:
            matches = wanted < years[0]
        elif "after" in low:
            matches = wanted > years[0]
        else:
            matches = wanted == years[0]
        if matches:
            hits.append(option)
    return hits[0] if len(hits) == 1 else None


def skill_options(options: Iterable[str], skills: Iterable[str]) -> list[str]:
    """Exact names and explicit aliases; punctuation is significant (C/C++/C#)."""

    def canonical(value: str) -> str:
        value = re.sub(r"\s*\(programming language\)\s*$", "", value.casefold()).strip()
        return {
            "cpp": "c++",
            "c plus plus": "c++",
            "c sharp": "c#",
            "csharp": "c#",
            "js": "javascript",
            "ts": "typescript",
        }.get(value, value)

    known = {canonical(skill) for skill in skills}
    return [option for option in options if canonical(option) in known]


def high_school_year(education: Iterable[object]) -> str:
    starts = [
        str(getattr(row, "start", ""))[:4]
        for row in education
        if re.search(r"bachelor|associate", str(getattr(row, "degree_level", "")), re.I)
        and re.match(r"\d{4}", str(getattr(row, "start", "")))
    ]
    return min(starts, default="")
