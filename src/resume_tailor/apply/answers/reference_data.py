"""Fixed option lists the Profile page offers and the fill code matches against.

One source of truth for countries (with dial codes), subdivisions and the self-ID answer
sets, so the picker the applicant sees and the aliases a form is matched with cannot
drift apart. Pure data, no LLM.
"""

from __future__ import annotations

from typing import Any

from resume_tailor.apply.answers import education

#: ISO2|name|dial code|aliases (``;``-separated). Dial codes shared by several countries
#: ("+1") are told apart by name, which is why the phone picker stores a region too.
_COUNTRIES = """\
AF|Afghanistan|93|
AL|Albania|355|
DZ|Algeria|213|
AS|American Samoa|1684|
AD|Andorra|376|
AO|Angola|244|
AI|Anguilla|1264|
AG|Antigua and Barbuda|1268|
AR|Argentina|54|
AM|Armenia|374|
AW|Aruba|297|
AU|Australia|61|
AT|Austria|43|
AZ|Azerbaijan|994|
BS|Bahamas|1242|
BH|Bahrain|973|
BD|Bangladesh|880|
BB|Barbados|1246|
BY|Belarus|375|
BE|Belgium|32|
BZ|Belize|501|
BJ|Benin|229|
BM|Bermuda|1441|
BT|Bhutan|975|
BO|Bolivia|591|
BA|Bosnia and Herzegovina|387|
BW|Botswana|267|
BR|Brazil|55|Brasil
VG|British Virgin Islands|1284|
BN|Brunei|673|
BG|Bulgaria|359|
BF|Burkina Faso|226|
BI|Burundi|257|
KH|Cambodia|855|
CM|Cameroon|237|
CA|Canada|1|
CV|Cape Verde|238|Cabo Verde
KY|Cayman Islands|1345|
CF|Central African Republic|236|
TD|Chad|235|
CL|Chile|56|
CN|China|86|People's Republic of China;PRC
CO|Colombia|57|
KM|Comoros|269|
CG|Congo|242|Republic of the Congo
CD|Congo (DRC)|243|Democratic Republic of the Congo;DR Congo
CK|Cook Islands|682|
CR|Costa Rica|506|
CI|Cote d'Ivoire|225|Ivory Coast
HR|Croatia|385|
CU|Cuba|53|
CW|Curacao|599|
CY|Cyprus|357|
CZ|Czechia|420|Czech Republic
DK|Denmark|45|
DJ|Djibouti|253|
DM|Dominica|1767|
DO|Dominican Republic|1809|
EC|Ecuador|593|
EG|Egypt|20|
SV|El Salvador|503|
GQ|Equatorial Guinea|240|
ER|Eritrea|291|
EE|Estonia|372|
SZ|Eswatini|268|Swaziland
ET|Ethiopia|251|
FK|Falkland Islands|500|
FO|Faroe Islands|298|
FJ|Fiji|679|
FI|Finland|358|
FR|France|33|
GF|French Guiana|594|
PF|French Polynesia|689|
GA|Gabon|241|
GM|Gambia|220|
GE|Georgia|995|
DE|Germany|49|Deutschland
GH|Ghana|233|
GI|Gibraltar|350|
GR|Greece|30|
GL|Greenland|299|
GD|Grenada|1473|
GP|Guadeloupe|590|
GU|Guam|1671|
GT|Guatemala|502|
GN|Guinea|224|
GW|Guinea-Bissau|245|
GY|Guyana|592|
HT|Haiti|509|
HN|Honduras|504|
HK|Hong Kong|852|Hong Kong SAR
HU|Hungary|36|
IS|Iceland|354|
IN|India|91|
ID|Indonesia|62|
IR|Iran|98|
IQ|Iraq|964|
IE|Ireland|353|
IL|Israel|972|
IT|Italy|39|
JM|Jamaica|1876|
JP|Japan|81|
JO|Jordan|962|
KZ|Kazakhstan|7|
KE|Kenya|254|
KI|Kiribati|686|
XK|Kosovo|383|
KW|Kuwait|965|
KG|Kyrgyzstan|996|
LA|Laos|856|
LV|Latvia|371|
LB|Lebanon|961|
LS|Lesotho|266|
LR|Liberia|231|
LY|Libya|218|
LI|Liechtenstein|423|
LT|Lithuania|370|
LU|Luxembourg|352|
MO|Macau|853|Macao
MG|Madagascar|261|
MW|Malawi|265|
MY|Malaysia|60|
MV|Maldives|960|
ML|Mali|223|
MT|Malta|356|
MH|Marshall Islands|692|
MQ|Martinique|596|
MR|Mauritania|222|
MU|Mauritius|230|
MX|Mexico|52|
FM|Micronesia|691|
MD|Moldova|373|
MC|Monaco|377|
MN|Mongolia|976|
ME|Montenegro|382|
MS|Montserrat|1664|
MA|Morocco|212|
MZ|Mozambique|258|
MM|Myanmar|95|Burma
NA|Namibia|264|
NR|Nauru|674|
NP|Nepal|977|
NL|Netherlands|31|The Netherlands;Holland
NC|New Caledonia|687|
NZ|New Zealand|64|
NI|Nicaragua|505|
NE|Niger|227|
NG|Nigeria|234|
KP|North Korea|850|
MK|North Macedonia|389|Macedonia
MP|Northern Mariana Islands|1670|
NO|Norway|47|
OM|Oman|968|
PK|Pakistan|92|
PW|Palau|680|
PS|Palestine|970|
PA|Panama|507|
PG|Papua New Guinea|675|
PY|Paraguay|595|
PE|Peru|51|
PH|Philippines|63|
PL|Poland|48|
PT|Portugal|351|
PR|Puerto Rico|1787|
QA|Qatar|974|
RE|Reunion|262|
RO|Romania|40|
RU|Russia|7|Russian Federation
RW|Rwanda|250|
WS|Samoa|685|
SM|San Marino|378|
ST|Sao Tome and Principe|239|
SA|Saudi Arabia|966|
SN|Senegal|221|
RS|Serbia|381|
SC|Seychelles|248|
SL|Sierra Leone|232|
SG|Singapore|65|
SK|Slovakia|421|
SI|Slovenia|386|
SB|Solomon Islands|677|
SO|Somalia|252|
ZA|South Africa|27|
KR|South Korea|82|Korea;Republic of Korea
SS|South Sudan|211|
ES|Spain|34|
LK|Sri Lanka|94|
KN|St. Kitts and Nevis|1869|Saint Kitts and Nevis
LC|St. Lucia|1758|Saint Lucia
VC|St. Vincent and the Grenadines|1784|Saint Vincent and the Grenadines
SD|Sudan|249|
SR|Suriname|597|
SE|Sweden|46|
CH|Switzerland|41|
SY|Syria|963|
TW|Taiwan|886|
TJ|Tajikistan|992|
TZ|Tanzania|255|
TH|Thailand|66|
TL|Timor-Leste|670|East Timor
TG|Togo|228|
TO|Tonga|676|
TT|Trinidad and Tobago|1868|
TN|Tunisia|216|
TR|Turkey|90|Turkiye
TM|Turkmenistan|993|
TC|Turks and Caicos Islands|1649|
TV|Tuvalu|688|
UG|Uganda|256|
UA|Ukraine|380|
AE|United Arab Emirates|971|UAE
GB|United Kingdom|44|UK;Great Britain;England;Britain
US|United States|1|USA;U.S.;U.S.A.;United States of America;America
VI|U.S. Virgin Islands|1340|US Virgin Islands
UY|Uruguay|598|
UZ|Uzbekistan|998|
VU|Vanuatu|678|
VA|Vatican City|39|
VE|Venezuela|58|
VN|Vietnam|84|Viet Nam
YE|Yemen|967|
ZM|Zambia|260|
ZW|Zimbabwe|263|
"""

#: code|name for the subdivisions forms ask for as "State".
_US_STATES = """\
AL|Alabama
AK|Alaska
AZ|Arizona
AR|Arkansas
CA|California
CO|Colorado
CT|Connecticut
DE|Delaware
DC|District of Columbia
FL|Florida
GA|Georgia
HI|Hawaii
ID|Idaho
IL|Illinois
IN|Indiana
IA|Iowa
KS|Kansas
KY|Kentucky
LA|Louisiana
ME|Maine
MD|Maryland
MA|Massachusetts
MI|Michigan
MN|Minnesota
MS|Mississippi
MO|Missouri
MT|Montana
NE|Nebraska
NV|Nevada
NH|New Hampshire
NJ|New Jersey
NM|New Mexico
NY|New York
NC|North Carolina
ND|North Dakota
OH|Ohio
OK|Oklahoma
OR|Oregon
PA|Pennsylvania
RI|Rhode Island
SC|South Carolina
SD|South Dakota
TN|Tennessee
TX|Texas
UT|Utah
VT|Vermont
VA|Virginia
WA|Washington
WV|West Virginia
WI|Wisconsin
WY|Wyoming
AS|American Samoa
GU|Guam
MP|Northern Mariana Islands
PR|Puerto Rico
VI|U.S. Virgin Islands
AA|Armed Forces Americas
AE|Armed Forces Europe
AP|Armed Forces Pacific
"""
_CA_PROVINCES = """\
AB|Alberta
BC|British Columbia
MB|Manitoba
NB|New Brunswick
NL|Newfoundland and Labrador
NS|Nova Scotia
NT|Northwest Territories
NU|Nunavut
ON|Ontario
PE|Prince Edward Island
QC|Quebec
SK|Saskatchewan
YT|Yukon
"""


def _rows(block: str) -> list[list[str]]:
    return [line.split("|") for line in block.splitlines() if line.strip()]


COUNTRIES: list[dict[str, Any]] = [
    {
        "code": code,
        "name": name,
        "dial": f"+{dial}",
        "aliases": [alias for alias in aliases.split(";") if alias],
    }
    for code, name, dial, aliases in _rows(_COUNTRIES)
]
SUBDIVISIONS: dict[str, list[dict[str, str]]] = {
    "United States": [{"code": code, "name": name} for code, name in _rows(_US_STATES)],
    "Canada": [{"code": code, "name": name} for code, name in _rows(_CA_PROVINCES)],
}

#: Self-identification answer sets. "decline" picks a form's decline option; blank skips
#: the question. Values stay the strings `field_matcher.eeo_tiers` already understands.
PRONOUNS = ["He/him", "She/her", "They/them"]
GENDERS = ["Male", "Female", "Non-binary"]
RACES = [
    "American Indian or Alaska Native",
    "Asian",
    "Black or African American",
    "Native Hawaiian or Other Pacific Islander",
    "White",
    "Two or More Races",
]
RACE_DETAILS: dict[str, list[str]] = {
    "American Indian or Alaska Native": ["American Indian", "Alaska Native"],
    "Asian": [
        "Asian Indian", "Chinese", "Filipino", "Japanese", "Korean", "Vietnamese",
        "Pakistani", "Bangladeshi", "Thai", "Cambodian", "Taiwanese", "Other Asian",
    ],
    "Black or African American": [
        "African American", "Nigerian", "Ethiopian", "Jamaican", "Haitian", "Other Black",
    ],
    "Native Hawaiian or Other Pacific Islander": [
        "Native Hawaiian", "Samoan", "Guamanian or Chamorro", "Tongan", "Other Pacific Islander",
    ],
    "White": ["European", "Middle Eastern or North African", "Other White"],
    "Two or More Races": [],
}
DISABILITY = ["Yes", "No"]

_BY_NAME = {country["name"].casefold(): country for country in COUNTRIES}
for _country in COUNTRIES:
    for _alias in _country["aliases"]:
        _BY_NAME.setdefault(_alias.casefold(), _country)


def country(name: str) -> dict[str, Any] | None:
    """The country a name or alias ("USA", "UK") stands for."""
    return _BY_NAME.get(name.strip().casefold())


def region_key(region: str) -> str:
    """Lowercased canonical country name for a region ("USA" -> "united states"), else
    the region as typed, lowercased; what phone-menu labels are compared against."""
    found = country(region)
    return (found["name"] if found else region).strip().casefold()


def region_identifiers(region: str) -> set[str]:
    """Short identifiers a country-valued option may carry ("us", "usa", "gb", "uk")."""
    found = country(region)
    if found is None:
        return set()
    return {found["code"].casefold(), *(a.casefold() for a in found["aliases"] if len(a) <= 4)}


def region_dial(region: str) -> str:
    """The calling code of a region ("+44" for "UK"), blank when unknown."""
    found = country(region)
    return found["dial"] if found else ""


def phone_label(code: str, region: str) -> str:
    """``"United States (+1)"``: the phone picker's visible text."""
    found = country(region)
    return f"{found['name']} ({found['dial']})" if found else code


def _subdivision(state: str, country_name: str) -> dict[str, str] | None:
    wanted = state.strip().casefold()
    for entry in SUBDIVISIONS.get(country_name, []):
        if wanted in {entry["code"].casefold(), entry["name"].casefold()}:
            return entry
    return None


def state_code(state: str, country_name: str = "United States") -> str:
    """``"California"`` -> ``"CA"`` (blank when unknown); a code passes through upcased."""
    entry = _subdivision(state, country_name)
    return entry["code"] if entry else ""


def state_name(state: str, country_name: str = "United States") -> str:
    """``"CA"`` -> ``"California"`` (blank when unknown)."""
    entry = _subdivision(state, country_name)
    return entry["name"] if entry else ""


def options() -> dict[str, Any]:
    """Everything the Profile page's pickers need, in one payload."""
    return {
        "countries": COUNTRIES,
        "subdivisions": SUBDIVISIONS,
        "pronouns": PRONOUNS,
        "genders": GENDERS,
        "races": RACES,
        "race_details": RACE_DETAILS,
        "disability": DISABILITY,
        "education_levels": list(education.LEVELS),
        "education_level_aliases": dict(education.LEVEL_BY_ALIAS),
    }
