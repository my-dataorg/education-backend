from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.grade_bands import GRADE_BANDS
from app.models import Section, SectionMember, TeacherGradeBand
from app.roles import TEACHER_ROLES
from app.services.institutes import get_membership


def list_teacher_grade_bands(db: Session, institute_id: str, user_id: str) -> list[str]:
    found = set(
        db.scalars(
            select(TeacherGradeBand.grade_band).where(
                TeacherGradeBand.institute_id == institute_id,
                TeacherGradeBand.user_id == user_id,
            )
        ).all()
    )
    return [b for b in GRADE_BANDS if b in found]


def grade_bands_by_user(db: Session, institute_id: str) -> dict[str, list[str]]:
    rows = db.execute(
        select(TeacherGradeBand.user_id, TeacherGradeBand.grade_band).where(
            TeacherGradeBand.institute_id == institute_id
        )
    )
    out: dict[str, list[str]] = {}
    for user_id, band in rows:
        out.setdefault(user_id, []).append(band)
    for user_id, bands in out.items():
        out[user_id] = [b for b in GRADE_BANDS if b in bands]
    return out


def set_teacher_grade_bands(
    db: Session, institute_id: str, user_id: str, grade_bands: list[str]
) -> list[str]:
    member = get_membership(db, institute_id, user_id)
    if not member:
        raise ValueError("User is not an institute member")
    if member.role not in TEACHER_ROLES:
        raise ValueError("Only teaching staff can have grade bands")
    unique = list(dict.fromkeys(grade_bands))
    if not unique:
        raise ValueError("Choose at least one grade band")
    if any(b not in GRADE_BANDS for b in unique):
        raise ValueError("Invalid grade band")
    assigned = list(
        db.scalars(
            select(Section)
            .join(SectionMember, SectionMember.section_id == Section.id)
            .where(
                Section.institute_id == institute_id,
                SectionMember.user_id == user_id,
                SectionMember.member_type == "teacher",
            )
        )
    )
    kept = set(unique)
    for section in assigned:
        if section.grade_band not in kept:
            raise ValueError("Cannot remove a band used on an assigned section")
    db.execute(
        delete(TeacherGradeBand).where(
            TeacherGradeBand.institute_id == institute_id,
            TeacherGradeBand.user_id == user_id,
        )
    )
    for band in unique:
        db.add(TeacherGradeBand(institute_id=institute_id, user_id=user_id, grade_band=band))
    db.commit()
    return list_teacher_grade_bands(db, institute_id, user_id)
