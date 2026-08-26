from datetime import date

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.models import Assignment, Base, Institute, InstituteMember, Section, SectionMember, Submission
from app.services.pending_work import list_pending_work


def _db() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def _seed_institute(db: Session) -> None:
    db.add(Institute(id="i1", name="School", join_code="ABC123"))
    db.add(InstituteMember(institute_id="i1", user_id="s1", role="student"))
    db.add(InstituteMember(institute_id="i1", user_id="t1", role="teacher"))
    db.add(InstituteMember(institute_id="i1", user_id="a1", role="admin"))
    db.add(Section(id="sec1", institute_id="i1", name="A", class_name="7"))
    db.commit()


def test_non_member_raises():
    db = _db()
    _seed_institute(db)
    try:
        list_pending_work(db, "i1", "nobody")
        raise AssertionError("expected PermissionError")
    except PermissionError:
        pass


def test_student_with_no_section_gets_enroll_item():
    db = _db()
    _seed_institute(db)
    items = list_pending_work(db, "i1", "s1")
    assert len(items) == 1
    assert items[0]["kind"] == "enroll_in_section"


def test_teacher_with_no_section_gets_enroll_item():
    db = _db()
    _seed_institute(db)
    items = list_pending_work(db, "i1", "t1")
    assert items[0]["kind"] == "enroll_in_section"


def test_admin_gets_empty_list():
    db = _db()
    _seed_institute(db)
    assert list_pending_work(db, "i1", "a1") == []


def test_student_unsubmitted_assignment():
    db = _db()
    _seed_institute(db)
    db.add(SectionMember(section_id="sec1", user_id="s1", member_type="student"))
    db.add(Assignment(id="a1", section_id="sec1", title="Lab report", description="", created_by="t1", due_date=date(2026, 9, 1)))
    db.add(Assignment(id="a2", section_id="sec1", title="Quiz", description="", created_by="t1"))
    db.add(Submission(assignment_id="a2", student_id="s1", content="done"))
    db.commit()
    items = list_pending_work(db, "i1", "s1")
    assert len(items) == 1
    assert items[0]["kind"] == "submit_assignment"
    assert items[0]["title"] == "Submit Lab report"
    assert items[0]["dueDate"] == date(2026, 9, 1)
    assert "sec1" in items[0]["href"]


def test_teacher_assignment_with_missing_submissions():
    db = _db()
    _seed_institute(db)
    db.add(InstituteMember(institute_id="i1", user_id="s2", role="student"))
    db.add(SectionMember(section_id="sec1", user_id="t1", member_type="teacher"))
    db.add(SectionMember(section_id="sec1", user_id="s1", member_type="student"))
    db.add(SectionMember(section_id="sec1", user_id="s2", member_type="student"))
    db.add(Assignment(id="a1", section_id="sec1", title="Lab report", description="", created_by="t1"))
    db.add(Submission(assignment_id="a1", student_id="s1", content="done"))
    db.commit()
    items = list_pending_work(db, "i1", "t1")
    assert len(items) == 1
    assert items[0]["kind"] == "review_assignment"
    assert "1 of 2" in items[0]["detail"]


def test_student_sees_all_incomplete_assignments_overdue_first():
    db = _db()
    _seed_institute(db)
    db.add(SectionMember(section_id="sec1", user_id="s1", member_type="student"))
    db.add(Assignment(id="a1", section_id="sec1", title="Upcoming", description="", created_by="t1", due_date=date(2099, 1, 1)))
    db.add(Assignment(id="a2", section_id="sec1", title="Overdue", description="", created_by="t1", due_date=date(2020, 1, 1)))
    db.add(Assignment(id="a3", section_id="sec1", title="Undated", description="", created_by="t1"))
    db.commit()
    items = list_pending_work(db, "i1", "s1")
    assert [i["title"] for i in items] == [
        "Submit Overdue",
        "Submit Upcoming",
        "Submit Undated",
    ]
    assert "Overdue 2020-01-01" in items[0]["detail"]


def test_teacher_sees_every_assignment_with_missing_work():
    db = _db()
    _seed_institute(db)
    db.add(SectionMember(section_id="sec1", user_id="t1", member_type="teacher"))
    db.add(SectionMember(section_id="sec1", user_id="s1", member_type="student"))
    db.add(Assignment(id="a1", section_id="sec1", title="One", description="", created_by="t1", due_date=date(2020, 1, 1)))
    db.add(Assignment(id="a2", section_id="sec1", title="Two", description="", created_by="t1", due_date=date(2099, 1, 1)))
    db.commit()
    items = list_pending_work(db, "i1", "t1")
    assert len(items) == 2
    assert items[0]["title"] == "One still has missing work"
    assert items[0]["dueDate"] == date(2020, 1, 1)
