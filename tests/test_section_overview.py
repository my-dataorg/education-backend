from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.models import Base, Institute, InstituteMember, Section, SectionMember
from app.services.sections import get_section_overview


def _db() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def _setup(db: Session) -> None:
    db.add(Institute(id="i1", name="School", join_code="ABC123"))
    db.add(InstituteMember(institute_id="i1", user_id="t1", role="teacher"))
    db.add(InstituteMember(institute_id="i1", user_id="ethan", role="student"))
    db.add(Section(id="s1", institute_id="i1", name="A", class_name="9", grade_band="high"))
    db.add(SectionMember(section_id="s1", user_id="t1", member_type="teacher"))
    db.add(SectionMember(section_id="s1", user_id="ethan", member_type="student"))
    db.commit()


def test_teacher_overview_includes_enrolled_student(monkeypatch):
    monkeypatch.setattr(
        "app.services.sections.enrich_rows",
        lambda rows, **_kwargs: [
            {
                **row,
                "firstName": "Ethan",
                "lastName": "Hunt",
                "email": "ethanhunt@gmail.com",
                "username": "ethan hunt",
            }
            if row.get("userId") == "ethan"
            else row
            for row in rows
        ],
    )
    db = _db()
    _setup(db)
    overview = get_section_overview(db, "s1", "t1")
    assert overview["studentCount"] == 1
    student = overview["students"][0]
    assert student["userId"] == "ethan"
    assert student["firstName"] == "Ethan"
    assert student["email"] == "ethanhunt@gmail.com"
    assert [t["userId"] for t in overview["teachers"]] == ["t1"]


def test_student_overview_includes_roster_without_contact(monkeypatch):
    monkeypatch.setattr(
        "app.services.sections.enrich_rows",
        lambda rows, **_kwargs: [
            {
                **row,
                "firstName": "Ethan",
                "lastName": "Hunt",
                "email": "ethanhunt@gmail.com",
                "username": "ethan hunt",
            }
            for row in rows
        ],
    )
    db = _db()
    _setup(db)
    overview = get_section_overview(db, "s1", "ethan")
    assert [s["userId"] for s in overview["students"]] == ["ethan"]
    assert overview["students"][0]["firstName"] == "Ethan"
    assert "email" not in overview["students"][0]
    assert "username" not in overview["students"][0]
    assert "teachers" not in overview
