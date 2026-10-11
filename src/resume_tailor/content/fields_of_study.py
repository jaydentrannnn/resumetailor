"""Suggestions for the education editor's degree type, majors and minors.

Suggestions only: the editor accepts anything typed, and application forms map the
person's own wording onto each form's options (`apply/forms/field_matcher`).
"""

from __future__ import annotations

DEGREE_TYPES: tuple[str, ...] = (
    "B.A.", "B.S.", "B.B.A.", "B.F.A.", "B.Eng.", "B.Arch.", "B.Mus.", "B.S.N.",
    "Bachelor of Arts", "Bachelor of Science", "Bachelor of Business Administration",
    "Bachelor of Fine Arts", "Bachelor of Engineering",
    "A.A.", "A.S.", "Associate of Arts", "Associate of Science",
    "M.A.", "M.S.", "M.B.A.", "M.Eng.", "M.F.A.", "M.P.H.", "M.Ed.",
    "Master of Arts", "Master of Science", "Master of Business Administration",
    "Ph.D.", "J.D.", "M.D.",
)

FIELDS_OF_STUDY: tuple[str, ...] = (
    "Accounting", "Actuarial Science", "Advertising", "Aerospace Engineering",
    "African American Studies", "Agricultural Science", "American Studies", "Anthropology",
    "Applied Mathematics", "Architecture", "Art", "Art History", "Asian American Studies",
    "Asian Studies", "Astronomy", "Astrophysics", "Biochemistry", "Bioengineering",
    "Bioinformatics", "Biology", "Biomedical Engineering", "Biotechnology",
    "Business Administration", "Business Analytics", "Business Economics",
    "Chemical Engineering", "Chemistry", "Chinese", "Civil Engineering", "Classics",
    "Cognitive Science", "Communication", "Comparative Literature", "Computer Engineering",
    "Computer Science", "Construction Management", "Creative Writing", "Criminal Justice",
    "Criminology", "Cybersecurity", "Dance", "Data Science", "Design",
    "Digital Information Systems", "Drama", "Earth Science", "East Asian Studies",
    "Ecology", "Economics", "Education", "Electrical Engineering",
    "Electrical and Computer Engineering", "Engineering", "Engineering Management",
    "English", "Entrepreneurship", "Environmental Engineering", "Environmental Science",
    "Environmental Studies", "Ethnic Studies", "Exercise Science", "Fashion Design",
    "Film Studies", "Finance", "Fine Arts", "Food Science", "French", "Gender Studies",
    "Genetics", "Geography", "Geology", "German", "Global Studies", "Graphic Design",
    "Health Administration", "Health Sciences", "History", "Hospitality Management",
    "Human Biology", "Human Resources", "Humanities", "Industrial Design",
    "Industrial Engineering", "Information Systems", "Information Technology",
    "Informatics", "Interior Design", "International Business", "International Relations",
    "Italian", "Japanese", "Journalism", "Kinesiology", "Korean", "Latin American Studies",
    "Law", "Liberal Arts", "Linguistics", "Literature", "Management",
    "Management Information Systems", "Marine Biology", "Marketing",
    "Materials Science", "Mathematics", "Mechanical Engineering", "Media Studies",
    "Microbiology", "Molecular Biology", "Music", "Neuroscience", "Nursing", "Nutrition",
    "Operations Management", "Philosophy", "Physics", "Physiology", "Political Science",
    "Pre-Law", "Pre-Medicine", "Psychology", "Public Health", "Public Policy",
    "Public Relations", "Real Estate", "Religious Studies", "Russian", "Social Work",
    "Sociology", "Software Engineering", "Spanish", "Sports Management", "Statistics",
    "Supply Chain Management", "Sustainability", "Theater", "Urban Planning",
    "Urban Studies", "Visual Arts", "Women's Studies", "Zoology",
)
