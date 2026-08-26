from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.models import Base, Institute, InstituteMember, Section
from app.services.grade_bands import set_teacher_grade_bands
from app.services.sections import assign_section_member
from app.services.subjects import create_subject, set_teacher_subjects


def _db() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def test_teacher_needs_subject_and_qualification():
    db = _db()
    inst = Institute(id="i1", name="School", join_code="ABC123")
    db.add(inst)
    db.add(InstituteMember(institute_id="i1", user_id="t1", role="teacher"))
    db.add(Section(id="s1", institute_id="i1", name="A", class_name="10", grade_band="high"))
    db.commit()

    try:
        assign_section_member(db, "s1", "t1", "teacher")
        raise AssertionError("expected ValueError")
    except ValueError as e:
        assert "subjectId" in str(e)

    math = create_subject(db, "i1", "Math")
    try:
        assign_section_member(db, "s1", "t1", "teacher", math.id)
        raise AssertionError("expected ValueError")
    except ValueError as e:
        assert "not assigned" in str(e)

    set_teacher_subjects(db, "i1", "t1", [math.id])
    try:
        assign_section_member(db, "s1", "t1", "teacher", math.id)
        raise AssertionError("expected ValueError")
    except ValueError as e:
        assert "grade band" in str(e)

    set_teacher_grade_bands(db, "i1", "t1", ["high"])
    assert db.get(Section, "s1").grade_band == "high"
    row = assign_section_member(db, "s1", "t1", "teacher", math.id)
    assert row.subject_id == math.id

    db.add(Section(id="s2", institute_id="i1", name="A", class_name="3", grade_band="primary"))
    db.commit()
    try:
        assign_section_member(db, "s2", "t1", "teacher", math.id)
        raise AssertionError("expected ValueError")
    except ValueError as e:
        assert "grade band" in str(e)


def test_one_teacher_per_subject_in_section():
    db = _db()
    inst = Institute(id="i1", name="School", join_code="ABC123")
    db.add(inst)
    db.add(InstituteMember(institute_id="i1", user_id="t1", role="teacher"))
    db.add(InstituteMember(institute_id="i1", user_id="t2", role="teacher"))
    db.add(Section(id="s1", institute_id="i1", name="A", class_name="10", grade_band="high"))
    db.commit()
    math = create_subject(db, "i1", "Math")
    set_teacher_subjects(db, "i1", "t1", [math.id])
    set_teacher_subjects(db, "i1", "t2", [math.id])
    set_teacher_grade_bands(db, "i1", "t1", ["high"])
    set_teacher_grade_bands(db, "i1", "t2", ["high"])
    assign_section_member(db, "s1", "t1", "teacher", math.id)
    try:
        assign_section_member(db, "s1", "t2", "teacher", math.id)
        raise AssertionError("expected ValueError")
    except ValueError as e:
        assert "already has a teacher" in str(e)
