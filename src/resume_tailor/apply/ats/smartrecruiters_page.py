"""SmartRecruiters form selectors, injected scripts and small page checks."""

from __future__ import annotations

from typing import Any

from resume_tailor.apply.forms import field_matcher

#: Entries added per section at most; the packet is already bounded by the resume.
MAX_ENTRIES = 10

#: How long a typeahead may take to show its options (the location search is remote).
_OPTIONS_WAIT_S = 5.0

#: The location typeahead's "Cannot find your city? ... fill in manually" row.
_MANUAL_LOCATION = "goToManualLocationMode"

#: The option that commits the typed text as-is (title, company, institution).
_CUSTOM_OPTION = "#spl-custom-option"

_LOCATION = "div[data-test=personal-info-location] spl-autocomplete"

#: Selectors `filler.js` reports for controls this flow owns: both dropzones' shared
#: ``#file-input`` and the message box. Its records for them are dropped in `fill`.
HANDLED_SELECTORS = frozenset({"#file-input", "#hiring-manager-message-input"})

_RESUME = "div[data-test=resume-upload-container]"

_MESSAGE = "oc-textarea[data-test=hiring-manager-message-text] textarea"

_STATE_CODES = {
    "alabama": "AL", "alaska": "AK", "arizona": "AZ", "arkansas": "AR", "california": "CA",
    "colorado": "CO", "connecticut": "CT", "delaware": "DE", "florida": "FL", "georgia": "GA",
    "hawaii": "HI", "idaho": "ID", "illinois": "IL", "indiana": "IN", "iowa": "IA",
    "kansas": "KS", "kentucky": "KY", "louisiana": "LA", "maine": "ME", "maryland": "MD",
    "massachusetts": "MA", "michigan": "MI", "minnesota": "MN", "mississippi": "MS",
    "missouri": "MO", "montana": "MT", "nebraska": "NE", "nevada": "NV",
    "new hampshire": "NH", "new jersey": "NJ", "new mexico": "NM", "new york": "NY",
    "north carolina": "NC", "north dakota": "ND", "ohio": "OH", "oklahoma": "OK",
    "oregon": "OR", "pennsylvania": "PA", "rhode island": "RI", "south carolina": "SC",
    "south dakota": "SD", "tennessee": "TN", "texas": "TX", "utah": "UT", "vermont": "VT",
    "virginia": "VA", "washington": "WA", "west virginia": "WV", "wisconsin": "WI",
    "wyoming": "WY", "district of columbia": "DC",
}

_US = {"us", "usa", "united states", "united states of america"}

#: ``[value, text]`` of every option a typeahead host shows (the menu renders inside the
#: host's own shadow root, under ``spl-dropdown``; light DOM is searched too).
_OPTIONS_JS = r"""(host) => {
  const out = [];
  const walk = (root) => {
    for (const el of root.querySelectorAll('*')) {
      if (el.tagName === 'SPL-SELECT-OPTION') {
        const label = (el.textContent || '').replace(/\s+/g, ' ').trim();
        out.push([el.getAttribute('value') || '', label]);
      }
      if (el.shadowRoot) walk(el.shadowRoot);
    }
  };
  walk(host);
  if (host.shadowRoot) walk(host.shadowRoot);
  return out;
}"""

#: A typeahead host's committed value: a string (title/company/institution), a location
#: object, or null/"" when nothing is committed.
_HOST_VALUE_JS = "(host) => host.value === undefined ? null : host.value"

#: Saved entries of a section, as their visible text parts. The title/institution line
#: carries the date span ("AI Intern 2026 - 2026"), which is cut off.
_ENTRIES_JS = r"""([section, kind]) => {
  const root = document.querySelector(`div[data-test="${section}"]`);
  if (!root) return null;
  const text = (e) => e ? (e.innerText || e.textContent || '').replace(/\s+/g, ' ').trim() : '';
  const tag = kind === 'experience' ? 'oc-experience-entry' : 'oc-education-entry';
  const heading = kind === 'experience'
    ? '[data-test=experience-entry-title]' : '[data-test=education-entry-institution]';
  const saved = [...root.querySelectorAll(tag)]
    .filter(e => !e.querySelector('[data-test$="-edit-form"]'));
  return saved.map(e => {
    const first = e.querySelector(heading);
    const date = text(e.querySelector(`[data-test=${kind}-entry-date]`));
    let head = text(first);
    if (date && head.endsWith(date)) head = head.slice(0, head.length - date.length).trim();
    return kind === 'experience'
      ? {title: head, company: text(e.querySelector('[data-test=experience-entry-company]'))}
      : {school: head, major: text(e.querySelector('[data-test=education-entry-major]')),
         degree: text(e.querySelector('[data-test=education-entry-degree]'))};
  });
}"""

#: The resume dropzone's listed files: ``li.c-spl-file-list-item`` rows in its shadow
#: root, each with a ``.c-spl-file-list-item-name``.
_DROPZONE_FILES_JS = r"""(zone) => {
  const names = [];
  let listed = 0;
  const walk = (root) => {
    for (const el of root.querySelectorAll('*')) {
      if (el.matches('.c-spl-file-list-item')) listed += 1;
      if (el.matches('.c-spl-file-list-item-name')) names.push((el.textContent || '').trim());
      if (el.shadowRoot) walk(el.shadowRoot);
    }
  };
  walk(zone.shadowRoot || zone);
  return {names: names.filter(Boolean), listed};
}"""

#: The centre of ``el`` when a press there lands on ``el`` (``elementFromPoint`` followed
#: into open shadow roots, slotted nodes back through their slots); else null.
_POINT_JS = r"""(el) => {
  el.scrollIntoView({block: 'nearest'});
  const r = el.getBoundingClientRect();
  if (!r.width || !r.height) return null;
  const x = r.left + r.width / 2, y = r.top + r.height / 2;
  let hit = document.elementFromPoint(x, y);
  while (hit && hit.shadowRoot) {
    const inner = hit.shadowRoot.elementFromPoint(x, y);
    if (!inner || inner === hit) break;
    hit = inner;
  }
  for (let n = hit; n; n = n.assignedSlot || n.parentNode || n.host) if (n === el) return [x, y];
  return null;
}"""

def is_form(page: Any) -> bool:
    """Whether ``page`` shows the one-click application form."""
    return "/oneclick-ui/" in str(getattr(page, "url", "") or "")

def _present(locator: Any) -> bool:
    try:
        return locator.count() > 0
    except Exception:  # noqa: BLE001
        return False

def _same(value: str, wanted: str, key: str = "") -> bool:
    """Normalised equality, or (for a ``key`` like "school") the catalog's aliases."""
    a, b = field_matcher.normalize(value or ""), field_matcher.normalize(wanted or "")
    if a == b:
        return True
    if not (key and a and b):
        return False
    return bool(field_matcher.closest_option([value], wanted, key=key)
                or field_matcher.closest_option([wanted], value, key=key))
