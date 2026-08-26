from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.models import Base, Institute, InstituteMember, Section
from app.services.classes import create_class, create_section, get_or_create_class
from app.services.sections import require_section_subject_teacher
from app.services.grade_bands import set_teacher_grade_bands
from app.services.sections import assign_section_member
from app.services.subjects import create_subject, set_teacher_subjects


def _db() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def test_sections_share_one_class_and_band():
    db = _db()
    db.add(Institute(id="i1", name="School", join_code="ABC123"))
    db.add(InstituteMember(institute_id="i1", user_id="a1", role="admin"))
    db.commit()
    cls = create_class(db, "i1", "10", "high")
    a = create_section(db, "i1", cls.id, "A", None)
    b = create_section(db, "i1", cls.id, "B", None)
    assert a.class_id == b.class_id == cls.id
    assert a.grade_band == b.grade_band == "high"
    try:
        get_or_create_class(db, "i1", "10", "primary")
        raise AssertionError("expected ValueError")
    except ValueError as e:
        assert "grade band" in str(e)


def test_teacher_only_posts_own_subject():
    db = _db()
    db.add(Institute(id="i1", name="School", join_code="ABC123"))
    db.add(InstituteMember(institute_id="i1", user_id="t1", role="teacher"))
    db.add(InstituteMember(institute_id="i1", user_id="t2", role="teacher"))
    db.add(Section(id="s1", institute_id="i1", name="A", class_name="10", grade_band="high"))
    db.commit()
    math = create_subject(db, "i1", "Math")
    eng = create_subject(db, "i1", "English")
    set_teacher_subjects(db, "i1", "t1", [math.id])
    set_teacher_subjects(db, "i1", "t2", [eng.id])
    set_teacher_grade_bands(db, "i1", "t1", ["high"])
    set_teacher_grade_bands(db, "i1", "t2", ["high"])
    assign_section_member(db, "s1", "t1", "teacher", math.id)
    assign_section_member(db, "s1", "t2", "teacher", eng.id)
    require_section_subject_teacher(db, "s1", "t1", math.id)
    try:
        require_section_subject_teacher(db, "s1", "t1", eng.id)
        raise AssertionError("expected PermissionError")
    except PermissionError:
        pass
