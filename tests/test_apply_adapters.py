"""Scoped ATS adapter interpretation over prepared application records."""

from resume_tailor.apply.adapters import GreenhouseAdapter
from resume_tailor.apply.field_types import FieldObservation
from resume_tailor.apply.packet import Packet, PacketEducation


def _field(label: str, control_id: str, row: str = "0") -> FieldObservation:
    return FieldObservation(
        snapshot_id="snapshot", field_id=control_id, frame_id="main",
        document_generation="document", label=label, repeater_row_id=row,
        control_kind="combobox" if "year" not in control_id else "number",
        constraints={"id": control_id},
    )


def test_greenhouse_education_uses_prepared_row_and_year():
    packet = Packet(
        job_id="one", built_at="2026-01-01",
        education=[
            PacketEducation(school="University of California, Irvine", degree_name="Bachelor of Science", major="Computer Science", end="2027-06"),
            PacketEducation(school="Another University", degree_name="Master of Science", major="Statistics", end="2029-05"),
        ],
    )
    adapter = GreenhouseAdapter()
    assert adapter.value_for(_field("School", "school--0"), "school", packet, {}) == "University of California, Irvine"
    assert adapter.value_for(_field("Degree", "degree--1", "1"), "degree_level", packet, {}) == "Master of Science"
    year = _field("End date year", "end-year--0")
    assert adapter.classify(year) == ("known", "education_end_year")
    assert adapter.value_for(year, "education_end_year", packet, {}) == "2027"
    assert adapter.value_for(_field("School", "school--2", "2"), "school", packet, {}) == ""
