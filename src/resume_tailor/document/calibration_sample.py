"""A built-in resume to calibrate against before the user has saved one.

`calibrate` measures the template with synthetic probe bullets; the resume only supplies
the surrounding page furniture (contact header, education, skills, a project link). A
brand-new profile has none yet — the upload wizard installs and calibrates before it
imports content — so this stands in with typical, plausible amounts of each. No LLM,
nothing personal: every value is a placeholder.
"""

from __future__ import annotations

from resume_tailor.content.data import (
    Bullet,
    Contact,
    Education,
    EducationSection,
    Experience,
    ExperienceSection,
    MasterResume,
    Project,
    ProjectSection,
    SkillGroup,
    SkillsSection,
)


def sample_resume() -> MasterResume:
    """A one-page-shaped resume covering every section kind the probes read from."""
    return MasterResume(
        contact=Contact(
            name="Alex Sample",
            email="alex.sample@example.com",
            phone="(555) 010-0100",
            location="Springfield, IL",
            linkedin="linkedin.com/in/alexsample",
            github="github.com/alexsample",
        ),
        sections=[
            EducationSection(
                id="education",
                title="Education",
                entries=[
                    Education(
                        school="University of Example",
                        degree="B.S. Computer Science",
                        dates="Sep 2021 - Jun 2025",
                        location="Springfield, IL",
                        coursework=["Data Structures", "Algorithms", "Databases"],
                    )
                ],
            ),
            ExperienceSection(
                id="experience",
                title="Experience",
                entries=[
                    Experience(
                        id="sample_job",
                        company="Example Corp",
                        title="Software Engineer Intern",
                        location="Springfield, IL",
                        start="2024-06",
                        end="2024-09",
                        bullets=[
                            Bullet(
                                id="sample_job_b1",
                                text="Built an internal reporting service used by 40 analysts.",
                            )
                        ],
                    )
                ],
            ),
            ProjectSection(
                id="projects",
                title="Projects",
                entries=[
                    Project(
                        id="sample_project",
                        name="Sample Project",
                        tech=["Python", "SQL"],
                        link="github.com/alexsample/project",
                        bullets=[
                            Bullet(
                                id="sample_project_b1",
                                text="Designed a small web app that tracks study sessions.",
                            )
                        ],
                    )
                ],
            ),
            SkillsSection(
                id="skills",
                title="Skills",
                entries=[
                    SkillGroup(label="Languages", items=["Python", "Java", "SQL"]),
                    SkillGroup(label="Tools", items=["Git", "Docker", "Linux"]),
                ],
            ),
        ],
    )
