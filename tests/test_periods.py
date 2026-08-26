from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.models import Base, Institute, InstituteMember, Section
from app.services.grade_bands import set_teacher_grade_bands
from app.services.periods import PeriodConflict, create_period
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
    db.add(Section(id="s1", institute_id="i1", name="A", class_name="5", grade_band="primary"))
    db.add(Section(id="s2", institute_id="i1", name="B", class_name="5", grade_band="primary"))
    db.commit()
    math = create_subject(db, "i1", "Math")
    set_teacher_subjects(db, "i1", "t1", [math.id])
    set_teacher_grade_bands(db, "i1", "t1", ["primary"])
    assign_section_member(db, "s1", "t1", "teacher", math.id)
    assign_section_member(db, "s2", "t1", "teacher", math.id)
    return math


def test_period_rejects_teacher_overlap_same_weekday():
    db = _db()
    math = _setup(db)
    create_period(db, "i1", "s1", math.id, "t1", "monday", "09:00", TERM)
    try:
        create_period(db, "i1", "s2", math.id, "t1", "monday", "09:00", TERM)
        raise AssertionError("expected PeriodConflict")
    except PeriodConflict:
        pass


def test_period_everyday_conflicts_with_weekday_same_hour():
    db = _db()
    math = _setup(db)
    create_period(db, "i1", "s1", math.id, "t1", "everyday", "09:00", TERM)
    try:
        create_period(db, "i1", "s2", math.id, "t1", "wednesday", "09:00", TERM)
        raise AssertionError("expected PeriodConflict")
    except PeriodConflict:
        pass


def test_period_weekday_conflicts_with_later_everyday():
    db = _db()
    math = _setup(db)
    create_period(db, "i1", "s1", math.id, "t1", "wednesday", "09:00", TERM)
    try:
        create_period(db, "i1", "s2", math.id, "t1", "everyday", "09:00", TERM)
        raise AssertionError("expected PeriodConflict")
    except PeriodConflict:
        pass


def test_period_allows_same_hour_on_different_weekdays():
    db = _db()
    math = _setup(db)
    create_period(db, "i1", "s1", math.id, "t1", "monday", "09:00", TERM)
    create_period(db, "i1", "s2", math.id, "t1", "tuesday", "09:00", TERM)


def test_period_allows_adjacent_hours_same_weekday():
    db = _db()
    math = _setup(db)
    create_period(db, "i1", "s1", math.id, "t1", "monday", "09:00", TERM)
    create_period(db, "i1", "s2", math.id, "t1", "monday", "10:00", TERM)


def test_period_rejects_section_overlap():
    db = _db()
    math = _setup(db)
    eng = create_subject(db, "i1", "English")
    db.add(InstituteMember(institute_id="i1", user_id="t2", role="teacher"))
    db.commit()
    set_teacher_subjects(db, "i1", "t2", [eng.id])
    set_teacher_grade_bands(db, "i1", "t2", ["primary"])
    assign_section_member(db, "s1", "t2", "teacher", eng.id)
    create_period(db, "i1", "s1", math.id, "t1", "friday", "10:00", TERM)
    try:
        create_period(db, "i1", "s1", eng.id, "t2", "friday", "10:00", TERM)
        raise AssertionError("expected PeriodConflict")
    except PeriodConflict:
        pass


def test_period_allows_same_slot_in_different_semester():
    db = _db()
    math = _setup(db)
    create_period(db, "i1", "s1", math.id, "t1", "monday", "09:00", TERM)
    create_period(db, "i1", "s2", math.id, "t1", "monday", "09:00", "Fall 2026")


def test_period_allows_several_weekdays_on_one_slot():
    db = _db()
    math = _setup(db)
    row = create_period(db, "i1", "s1", math.id, "t1", "friday,monday,tuesday", "09:00", TERM)
    assert row.weekday == "monday,tuesday,friday"


def test_period_rejects_everyday_combined_with_specific_days():
    db = _db()
    math = _setup(db)
    try:
        create_period(db, "i1", "s1", math.id, "t1", "everyday,monday", "09:00", TERM)
        raise AssertionError("expected ValueError")
    except ValueError as exc:
        assert "Everyday cannot be combined" in str(exc)


def test_period_multi_day_conflicts_on_shared_day():
    db = _db()
    math = _setup(db)
    create_period(db, "i1", "s1", math.id, "t1", "monday,wednesday", "09:00", TERM)
    try:
        create_period(db, "i1", "s2", math.id, "t1", "wednesday,friday", "09:00", TERM)
        raise AssertionError("expected PeriodConflict")
    except PeriodConflict:
        pass


def test_period_rejects_blank_semester():
    db = _db()
    math = _setup(db)
    try:
        create_period(db, "i1", "s1", math.id, "t1", "monday", "09:00", "   ")
        raise AssertionError("expected ValueError")
    except ValueError:
        pass
