"""Merging a second resume: pairing jobs and projects, and never losing a bullet."""

from __future__ import annotations

import pytest

from resume_tailor.content.data import (
    Bullet,
    Contact,
    Experience,
    ExperienceSection,
    MasterResume,
    Project,
    ProjectSection,
)
from resume_tailor.importing import import_merge, import_merge_plan


def _resume(*sections) -> MasterResume:
    contact = Contact(name="Ada Lovelace", email="ada@example.com")
    return MasterResume(contact=contact, sections=list(sections))


def _job(company: str, *bullets: str, id: str = "", title="Research Assistant", **fields):
    fields.setdefault("start", "2024-09")
    fields.setdefault("end", "2025-06")
    return Experience(
        id=id,
        company=company,
        title=title,
        bullets=[Bullet(id=f"{id or 'inc'}_b{i}", text=t) for i, t in enumerate(bullets, 1)],
        **fields,
    )


def _jobs(*entries: Experience, id="exp", title="EXPERIENCE") -> ExperienceSection:
    return ExperienceSection(id=id, title=title, entries=list(entries))


def test_same_title_and_dates_only_suggest_a_pair_the_student_confirms():
    """Two spellings of one employer with the same role and dates: the app cannot tell
    that from two employers, so it suggests the pair and merges only when picked."""
    existing = _resume(
        _jobs(_job("UCSD Economics Lab", "Cleaned 40k survey rows.", "Ran regressions.", id="lab"))
    )
    incoming = _resume(
        _jobs(
            _job(
                "UC San Diego Department of Economics",
                "Presented findings to faculty.",
                title="Economic Research Assistant",
            )
        )
    )

    [pair] = import_merge_plan.plan_merge(existing, incoming.sections).pairs
    assert (pair.match, pair.suggested, pair.suggested_name) == (None, "lab", "UCSD Economics Lab")

    apart, _ = import_merge.merge_into(existing, incoming)
    assert len(apart.experience) == 2

    merged, stats = import_merge.merge_into(existing, incoming, {pair.key: "lab"})
    assert [e.company for e in merged.experience] == ["UCSD Economics Lab"]
    assert [b.text for b in merged.experience[0].bullets] == [
        "Cleaned 40k survey rows.",
        "Ran regressions.",
        "Presented findings to faculty.",
    ]
    assert stats.added == []


def test_same_role_and_dates_at_another_employer_stay_two_jobs():
    existing = _resume(_jobs(_job("Stanford Psychology Lab", "Ran 30 study sessions.", id="psy")))
    incoming = _resume(_jobs(_job("Mayo Clinic Cardiology", "Coded 200 patient charts.")))

    merged, stats = import_merge.merge_into(existing, incoming)

    assert [e.company for e in merged.experience] == [
        "Stanford Psychology Lab",
        "Mayo Clinic Cardiology",
    ]
    assert [b.text for b in merged.experience[0].bullets] == ["Ran 30 study sessions."]
    assert not any("merged into" in w for w in stats.warnings)
    both = _resume(_jobs(*existing.sections[0].entries, _job("Mayo Clinic Cardiology", id="mayo")))
    assert import_merge_plan.find_duplicates(both.sections) == []


def test_titles_sharing_one_word_of_three_stay_two_jobs():
    existing = _resume(_jobs(_job("Acme", "Built a thing.", id="acme", title="Data Intern")))
    incoming = _resume(_jobs(_job("Beta", "Built another.", title="Research Intern")))

    merged, _ = import_merge.merge_into(existing, incoming)

    assert [e.company for e in merged.experience] == ["Acme", "Beta"]


def test_same_title_without_matching_dates_stays_two_jobs():
    existing = _resume(_jobs(_job("Acme", "Built a thing.", id="acme")))
    incoming = _resume(_jobs(_job("Beta", "Built another.", start="2022-01", end="2022-06")))

    merged, stats = import_merge.merge_into(existing, incoming)

    assert [e.company for e in merged.experience] == ["Acme", "Beta"]
    assert stats.added == ["Beta"]


def test_two_candidates_are_never_guessed():
    """Two existing jobs with the incoming one's title and dates: added as new."""
    existing = _resume(_jobs(_job("Lab A", "One.", id="a"), _job("Lab B", "Two.", id="b")))
    incoming = _resume(_jobs(_job("Lab C", "Three.")))

    merged, _ = import_merge.merge_into(existing, incoming)

    assert [e.company for e in merged.experience] == ["Lab A", "Lab B", "Lab C"]


def _acme(*bullets: Bullet) -> MasterResume:
    return _resume(
        _jobs(
            Experience(
                id="acme", company="Acme", title="Analyst", start="2024", end="2025",
                bullets=list(bullets),
            )
        )
    )


def _acme_upload(*texts: str) -> MasterResume:
    return _resume(_jobs(_job("Acme", *texts, title="Analyst", start="2024", end="2025")))


def test_added_words_refresh_the_bullet_and_keep_its_id_and_skills():
    existing = _acme(
        Bullet(id="acme_b1", text="Reduced report runtime by 30% using SQL.", tags=["SQL"]),
        Bullet(id="acme_b2", text="Mentored two interns."),
    )
    incoming = _acme_upload(
        "Reduced weekly report runtime by 30% using SQL.", "Automated a weekly dashboard."
    )

    merged, _ = import_merge.merge_into(existing, incoming)

    bullets = merged.experience[0].bullets
    assert [(b.id, b.text) for b in bullets] == [
        ("acme_b1", "Reduced weekly report runtime by 30% using SQL."),
        ("acme_b2", "Mentored two interns."),  # not in the upload, still here
        ("acme_b3", "Automated a weekly dashboard."),
    ]
    assert bullets[0].tags == ["SQL"]


def test_fewer_words_or_punctuation_keep_the_resume_wording():
    existing = _acme(Bullet(id="acme_b1", text="Reduced weekly report runtime by 30% using SQL."))
    incoming = _acme_upload("reduced report runtime by 30% using SQL")

    merged, _ = import_merge.merge_into(existing, incoming)

    assert [b.text for b in merged.experience[0].bullets] == [
        "Reduced weekly report runtime by 30% using SQL."
    ]


@pytest.mark.parametrize(
    ("old", "new"),
    [
        ("Opened 12 retail locations across Canada.", "Opened 12 retail locations across Mexico."),
        ("Reduced report runtime by 30% using SQL.", "Reduced report runtime by 35% using SQL."),
        ("Raised $1M in seed funding.", "Raised $1.5M in seed funding."),
    ],
)
def test_a_changed_word_or_number_keeps_both_bullets(old, new):
    existing = _acme(Bullet(id="acme_b1", text=old))
    incoming = _acme_upload(new)

    [pair] = import_merge_plan.plan_merge(existing, incoming.sections).pairs
    merged, _ = import_merge.merge_into(existing, incoming)

    assert pair.new_bullets == 1
    assert [b.text for b in merged.experience[0].bullets] == [old, new]


def test_an_empty_incoming_field_never_blanks_the_existing_one():
    existing = _resume(_jobs(_job("Acme", id="acme", location="Irvine, CA")))
    incoming = _resume(_jobs(_job("Acme", location="")))

    merged, _ = import_merge.merge_into(existing, incoming)

    assert merged.experience[0].location == "Irvine, CA"


def test_a_decision_overrides_the_proposed_pair():
    existing = _resume(_jobs(_job("Acme", "One.", id="acme"), _job("Beta", "Two.", id="beta", start="2020", end="2021")))
    incoming = _resume(_jobs(_job("Acme", "Three.")))
    key = "experience:0:0"

    as_new, stats = import_merge.merge_into(existing, incoming, {key: "new"})
    assert [e.company for e in as_new.experience].count("Acme") == 2
    assert stats.added == ["Acme"]

    into_beta, _ = import_merge.merge_into(existing, incoming, {key: "beta"})
    beta = next(e for e in into_beta.experience if e.id == "beta")
    assert beta.company == "Beta"  # a pair the student chose keeps the name it had
    assert [b.text for b in beta.bullets] == ["Two.", "Three."]
    assert len(into_beta.experience) == 2


def test_an_unknown_decision_falls_back_to_the_automatic_pair():
    existing = _resume(_jobs(_job("Acme", "One.", id="acme")))
    incoming = _resume(_jobs(_job("Acme", "Two.")))

    merged, _ = import_merge.merge_into(existing, incoming, {"experience:0:0": "missing"})

    assert len(merged.experience) == 1


def test_a_decision_follows_the_entry_when_the_resume_is_reordered():
    """Decisions name entries by id: moving sections after the review cannot send the
    upload to another employer."""
    acme = _job("Acme", "One.", id="acme", start="2020", end="2021")
    beta = _job("Beta", "Two.", id="beta", start="2022", end="2023")
    first = _resume(_jobs(acme, id="s1", title="WORK"), _jobs(beta, id="s2", title="MORE WORK"))
    incoming = _resume(_jobs(_job("Gamma", "Three.", start="2018", end="2019")))
    [pair] = import_merge_plan.plan_merge(first, incoming.sections).pairs

    reordered = _resume(*reversed(first.sections))
    merged, _ = import_merge.merge_into(reordered, incoming, {pair.key: "beta"})

    beta_after = next(e for e in merged.experience if e.id == "beta")
    assert [b.text for b in beta_after.bullets] == ["Two.", "Three."]
    assert import_merge_plan.resume_revision(first) != import_merge_plan.resume_revision(reordered)


def test_projects_pair_on_a_similar_name_only_with_the_same_dates():
    def project(name, text, id="", **dates):
        return Project(id=id, name=name, bullets=[Bullet(id=f"{id or 'p'}_b1", text=text)], **dates)

    def section(*entries):
        return ProjectSection(id="proj", title="PROJECTS", entries=list(entries))

    existing = _resume(section(project("Transit Optimizer", "Routed buses.", id="transit", start="2024-01", end="2024-05")))
    same_dates = _resume(section(project("Campus Transit Optimizer", "Cut wait times.", start="2024-01", end="2024-05")))
    undated = _resume(section(project("Campus Transit Optimizer", "Cut wait times.")))

    paired, _ = import_merge.merge_into(existing, same_dates)
    assert [p.name for p in paired.projects] == ["Transit Optimizer"]
    assert len(paired.projects[0].bullets) == 2

    apart, _ = import_merge.merge_into(existing, undated)
    assert len(apart.projects) == 2


def test_plan_lists_each_incoming_entry_with_its_pair_and_new_bullet_count():
    existing = _resume(_jobs(_job("Acme", "One.", "Two.", id="acme")))
    incoming = _resume(_jobs(_job("Acme", "One.", "Three."), _job("Zeta", "Four.", id="zeta", start="2021", end="2022")))

    plan = import_merge_plan.plan_merge(existing, incoming.sections)

    assert [(p.key, p.name, p.match, p.reason, p.new_bullets) for p in plan.pairs] == [
        ("experience:0:0", "Acme", "acme", "same name", 1),
        ("experience:0:1", "Zeta", None, "", 1),
    ]
    assert [(o.ref, o.kind) for o in plan.options] == [("acme", "experience")]
    assert plan.options[0].label.startswith("Acme")
    assert plan.revision == import_merge_plan.resume_revision(existing)
    assert plan.existing_empty is False
    assert import_merge_plan.plan_merge(_resume(), incoming.sections).existing_empty is True


def test_find_duplicates_needs_the_same_dates_even_for_the_same_name():
    resume = _resume(
        _jobs(
            _job("Acme", "Built a pipeline.", id="acme1"),
            _job("Acme", "Built a pipeline.", "Led a team.", id="acme2"),
            _job("Acme", "Promoted.", id="acme3", title="Lead", start="2025-07", end="2026-01"),
        )
    )

    pairs = import_merge_plan.find_duplicates(resume.sections)

    assert [(p.keep, p.drop, p.reason) for p in pairs] == [
        ("acme1", "acme2", "same name and dates")
    ]


def test_merge_duplicate_folds_bullets_and_removes_the_second_entry():
    resume = _resume(
        _jobs(
            _job("UCSD Economics Lab", "Ran regressions.", id="lab", location=""),
            _job(
                "UC San Diego Department of Economics",
                "Ran regressions.",
                "Presented to faculty.",
                id="dept",
                title="Economic Research Assistant",
                location="La Jolla, CA",
            ),
        )
    )
    # A similar title is not evidence of one employer, so this pair is not flagged...
    assert import_merge_plan.find_duplicates(resume.sections) == []

    # ...but merging two entries the student names still folds them together.
    merged = import_merge_plan.merge_duplicate(resume, "lab", "dept")

    [entry] = merged.experience
    assert entry.id == "lab" and entry.company == "UCSD Economics Lab"
    assert entry.location == "La Jolla, CA"  # filled from the other entry
    assert [b.text for b in entry.bullets] == ["Ran regressions.", "Presented to faculty."]


def test_find_duplicates_flags_a_name_that_grew_over_the_same_dates():
    resume = _resume(
        _jobs(
            _job("Acme Corp", "Built a pipeline.", id="acme"),
            _job("Acme Corp Consulting Division", "Led a team.", id="acmecd"),
        )
    )

    [pair] = import_merge_plan.find_duplicates(resume.sections)

    assert (pair.keep, pair.drop, pair.reason) == ("acme", "acmecd", "similar name and the same dates")


def test_merge_duplicate_refuses_ids_that_are_gone():
    resume = _resume(_jobs(_job("Acme", "One.", id="acme")))
    with pytest.raises(ValueError):
        import_merge_plan.merge_duplicate(resume, "acme", "missing")
