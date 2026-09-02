from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.models import Base, Institute, InstituteMember, Section, SectionMember
from app.services.grade_bands import set_teacher_grade_bands
from app.services.periods import create_period, list_my_classes_for_day
from app.services.sections import assign_section_member
from app.services.subjects import create_subject, set_teacher_subjects

TERM = "Summer 2026"


def _db() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def _setup(db: Session):
    db.add(Institute(id="i1", name="School", join_code="ABC123"))
    db.add(InstituteMember(institute_id="i1", user_id="t1", role="teacher"))
    db.add(InstituteMember(institute_id="i1", user_id="t2", role="teacher"))
    db.add(InstituteMember(institute_id="i1", user_id="s1", role="student"))
    db.add(Section(id="s1", institute_id="i1", name="A", class_name="9", grade_band="high"))
    db.commit()
    math = create_subject(db, "i1", "Mathematics")
    set_teacher_subjects(db, "i1", "t1", [math.id])
    set_teacher_grade_bands(db, "i1", "t1", ["high"])
    assign_section_member(db, "s1", "t1", "teacher", math.id)
    db.add(SectionMember(section_id="s1", user_id="s1", member_type="student"))
    db.commit()
    return math


def test_teacher_sees_only_own_classes_for_weekday():
    db = _db()
    math = _setup(db)
    create_period(db, "i1", "s1", math.id, "t1", "monday", "09:00", TERM)
    result = list_my_classes_for_day(db, "i1", "t1", "monday")
    assert result["weekday"] == "monday"
    assert len(result["items"]) == 1
    item = result["items"][0]
    assert item["className"] == "9"
    assert item["sectionName"] == "A"
    assert item["subjectName"] == "Mathematics"
    assert item["startTime"] == "09:00"
    assert item["endTime"] == "10:00"
    assert item["href"] == "/institutes/i1/sections/s1"


def test_teacher_skips_other_weekdays():
    db = _db()
    math = _setup(db)
    create_period(db, "i1", "s1", math.id, "t1", "monday", "09:00", TERM)
    result = list_my_classes_for_day(db, "i1", "t1", "tuesday")
    assert result["items"] == []


def test_everyday_shows_on_any_weekday():
    db = _db()
    math = _setup(db)
    create_period(db, "i1", "s1", math.id, "t1", "everyday", "09:00", TERM)
    result = list_my_classes_for_day(db, "i1", "t1", "wednesday")
    assert len(result["items"]) == 1


def test_other_teacher_does_not_see_period():
    db = _db()
    math = _setup(db)
    create_period(db, "i1", "s1", math.id, "t1", "monday", "09:00", TERM)
    result = list_my_classes_for_day(db, "i1", "t2", "monday")
    assert result["items"] == []


def test_student_sees_section_period():
    db = _db()
    math = _setup(db)
    create_period(db, "i1", "s1", math.id, "t1", "monday", "09:00", TERM)
    result = list_my_classes_for_day(db, "i1", "s1", "monday")
    assert len(result["items"]) == 1
    assert result["items"][0]["subjectName"] == "Mathematics"


def test_non_member_raises():
    db = _db()
    _setup(db)
    try:
        list_my_classes_for_day(db, "i1", "nobody", "monday")
        raise AssertionError("expected PermissionError")
    except PermissionError:
        pass


def test_classes_ordered_by_start_time():
    db = _db()
    math = _setup(db)
    create_period(db, "i1", "s1", math.id, "t1", "monday", "11:00", TERM)
    eng = create_subject(db, "i1", "English")
    set_teacher_subjects(db, "i1", "t1", [math.id, eng.id])
    assign_section_member(db, "s1", "t1", "teacher", eng.id)
    create_period(db, "i1", "s1", eng.id, "t1", "monday", "09:00", TERM)
    times = [item["startTime"] for item in list_my_classes_for_day(db, "i1", "t1", "monday")["items"]]
    assert times == ["09:00", "11:00"]


def test_invalid_weekday_raises():
    db = _db()
    _setup(db)
    try:
        list_my_classes_for_day(db, "i1", "t1", "funday")
        raise AssertionError("expected ValueError")
    except ValueError:
        pass


def test_multi_day_period_matches_listed_weekday():
    db = _db()
    math = _setup(db)
    create_period(db, "i1", "s1", math.id, "t1", "monday,wednesday", "09:00", TERM)
    assert len(list_my_classes_for_day(db, "i1", "t1", "wednesday")["items"]) == 1
    assert list_my_classes_for_day(db, "i1", "t1", "tuesday")["items"] == []


def test_unenrolled_student_does_not_see_period():
    db = _db()
    math = _setup(db)
    db.add(InstituteMember(institute_id="i1", user_id="s2", role="student"))
    db.commit()
    create_period(db, "i1", "s1", math.id, "t1", "monday", "09:00", TERM)
    assert list_my_classes_for_day(db, "i1", "s2", "monday")["items"] == []
