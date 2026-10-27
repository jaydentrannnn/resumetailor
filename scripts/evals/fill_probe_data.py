"""The made-up applicant `fill_probe.py` fills live forms with (no real person's data).

Every value is fictional: "quorvel.example" is a reserved test domain (RFC 2606), 555-01xx
numbers are reserved for fiction. `MARKERS` are the byte strings the probe's network guard
looks for, so a request carrying any of them never leaves the browser.
"""

from __future__ import annotations

from pathlib import Path

from resume_tailor.apply.answers.profile import ApplicantProfile, EEOAnswers
from resume_tailor.content import data as resume_data

FIRST, LAST = "Zyxta", "Quorvel"
EMAIL = "zyxta.quorvel@quorvel.example"
PHONE = "(916) 555-0147"

#: Whole values and the prefixes a keystroke recorder sends while they are typed.
MARKERS: tuple[bytes, ...] = (
    b"Zyxt",
    b"zyxt",
    b"ZYXT",
    b"Quorv",
    b"quorv",
    b"QUORV",
    b"5550147",
    b"555-0147",
    b"555) 0147",
    b"555 0147",
    b"555.0147",
)

#: The made-up applicant's other distinctive answers (school, employers, address, start
#: date, salary). Not identifying alone, but a write carrying one is saving the form, so
#: the guard blocks it and the audit checks every allowed request for them.
ANSWER_MARKERS: tuple[bytes, ...] = (
    b"California State University",
    b"Northwind",
    b"Campus Data Lab",
    b"Software Engineering Intern",
    b"Undergraduate Researcher",
    b"Sacramento",
    b"95814",
    b"2027-06-15",
    b"110000",
    b"140000",
)

RESUME = resume_data.MasterResume(
    contact=resume_data.Contact(
        name=f"{FIRST} {LAST}",
        email=EMAIL,
        phone=PHONE,
        location="Sacramento, CA",
        linkedin="linkedin.com/in/zyxta-quorvel",
        github="github.com/zyxtaquorvel",
    ),
    sections=[
        resume_data.EducationSection(
            id="education",
            title="Education",
            entries=[
                resume_data.Education(
                    school="California State University, Sacramento",
                    degree="B.S. in Computer Science",
                    dates="Sep 2023 – Jun 2027",
                    location="Sacramento, CA",
                    gpa="3.7",
                    start="2023-09",
                    end="2027-06",
                    degree_type="Bachelor of Science",
                    majors=["Computer Science"],
                    coursework=["Data Structures", "Operating Systems", "Machine Learning"],
                ),
            ],
        ),
        resume_data.ExperienceSection(
            id="experience",
            title="Experience",
            entries=[
                resume_data.Experience(
                    id="e1",
                    company="Northwind Analytics",
                    title="Software Engineering Intern",
                    location="San Diego, CA",
                    start="2025-06",
                    end="2025-09",
                    bullets=[
                        resume_data.Bullet(
                            id="b1",
                            text="Built a Python service that cut report generation time by 40%",
                            tags=["Python"],
                        ),
                        resume_data.Bullet(
                            id="b2",
                            text="Wrote React dashboards used by 30 analysts",
                            tags=["React", "TypeScript"],
                        ),
                    ],
                ),
                resume_data.Experience(
                    id="e2",
                    company="Campus Data Lab",
                    title="Undergraduate Researcher",
                    location="Sacramento, CA",
                    start="2024-09",
                    end="",
                    bullets=[
                        resume_data.Bullet(
                            id="b3",
                            text="Trained PyTorch models for sensor anomaly detection",
                            tags=["PyTorch", "Python"],
                        )
                    ],
                ),
            ],
        ),
    ],
)

PROFILE = ApplicantProfile(
    first_name=FIRST,
    last_name=LAST,
    email=EMAIL,
    phone=PHONE,
    phone_device_type="Mobile",
    phone_country_code="+1",
    phone_country_region="United States",
    address_line1="100 Quorvel Way",
    city="Sacramento",
    state="California",
    postal_code="95814",
    country="United States",
    linkedin_url="https://linkedin.com/in/zyxta-quorvel",
    github_url="https://github.com/zyxtaquorvel",
    work_authorization="citizen",
    authorized_to_work=True,
    authorization_country="United States",
    authorization_countries=["United States"],
    citizenship="United States",
    requires_sponsorship_now=False,
    requires_sponsorship_future=False,
    earliest_start="2027-06-15",
    highest_education_obtained="High school diploma",
    salary_hourly_min=30,
    salary_hourly_max=45,
    salary_yearly_min=110000,
    salary_yearly_max=140000,
    willing_to_relocate=True,
    over_18=True,
    relatives_at_company=False,
    subject_to_noncompete=False,
    graduation_date="2027-06",
    class_year="junior",
    high_school_graduation_year="2023",
    consider_other_positions=True,
    security_clearance="none",
    drivers_license=True,
    eeo=EEOAnswers(),
    auto_accept_notices=True, auto_accept_agreements=True,
)

SKILLS = ["Python", "React", "PyTorch", "TypeScript"]


def write_pdf(path: Path) -> None:
    """A one-page PDF resume for the made-up applicant (no PDF library needed)."""
    text = f"{FIRST} {LAST}  Software Engineering Intern  Python React PyTorch"
    stream = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode()
    objs = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R "
        b"/Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out, offsets = bytearray(b"%PDF-1.4\n"), []
    for number, body in enumerate(objs, 1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % number + body + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1)
    out += b"".join(b"%010d 00000 n \n" % offset for offset in offsets)
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, xref)
    path.write_bytes(bytes(out))
