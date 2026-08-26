from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models import Section, SectionMember, Subject, TeacherSubject
from app.roles import TEACHER_ROLES
from app.services.institutes import get_membership


def list_subjects(db: Session, institute_id: str) -> list[Subject]:
    return list(
        db.scalars(
            select(Subject).where(Subject.institute_id == institute_id).order_by(Subject.name)
        )
    )


def create_subject(db: Session, institute_id: str, name: str) -> Subject:
    trimmed = name.strip()
    if not trimmed:
        raise ValueError("Subject name is required")
    existing = db.scalar(
        select(Subject).where(
            Subject.institute_id == institute_id,
            Subject.name == trimmed,
        )
    )
    if existing:
        raise ValueError("Subject already exists")
    row = Subject(institute_id=institute_id, name=trimmed)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def delete_subject(db: Session, institute_id: str, subject_id: str) -> None:
    subject = db.scalar(
        select(Subject).where(Subject.id == subject_id, Subject.institute_id == institute_id)
    )
    if not subject:
        raise ValueError("Subject not found")
    in_use = db.scalar(
        select(SectionMember).where(
            SectionMember.subject_id == subject_id,
            SectionMember.member_type == "teacher",
        )
    )
    if in_use:
        raise ValueError("Subject is assigned to a section")
    db.execute(delete(TeacherSubject).where(TeacherSubject.subject_id == subject_id))
    db.delete(subject)
    db.commit()


def list_teacher_subjects(db: Session, institute_id: str, user_id: str) -> list[Subject]:
    return list(
        db.scalars(
            select(Subject)
            .join(TeacherSubject, TeacherSubject.subject_id == Subject.id)
            .where(
                TeacherSubject.institute_id == institute_id,
                TeacherSubject.user_id == user_id,
            )
            .order_by(Subject.name)
        )
    )


def subjects_by_user(db: Session, institute_id: str) -> dict[str, list[dict]]:
    rows = db.execute(
        select(TeacherSubject.user_id, Subject)
        .join(Subject, Subject.id == TeacherSubject.subject_id)
        .where(TeacherSubject.institute_id == institute_id)
        .order_by(Subject.name)
    )
    out: dict[str, list[dict]] = {}
    for user_id, subject in rows:
        out.setdefault(user_id, []).append({"id": subject.id, "name": subject.name})
    return out


def set_teacher_subjects(db: Session, institute_id: str, user_id: str, subject_ids: list[str]) -> list[Subject]:
    member = get_membership(db, institute_id, user_id)
    if not member:
        raise ValueError("User is not an institute member")
    if member.role not in TEACHER_ROLES:
        raise ValueError("Only teaching staff can have subjects")
    unique_ids = list(dict.fromkeys(subject_ids))
    if not unique_ids:
        raise ValueError("Choose at least one subject")
    subjects = list(
        db.scalars(
            select(Subject).where(Subject.institute_id == institute_id, Subject.id.in_(unique_ids))
        )
    )
    if len(subjects) != len(unique_ids):
        raise ValueError("Subject not found")
    assigned = list(
        db.scalars(
            select(SectionMember)
            .join(Section, Section.id == SectionMember.section_id)
            .where(
                Section.institute_id == institute_id,
                SectionMember.user_id == user_id,
                SectionMember.member_type == "teacher",
            )
        )
    )
    kept = {s.id for s in subjects}
    for row in assigned:
        if row.subject_id and row.subject_id not in kept:
            raise ValueError("Cannot remove a subject that is assigned to a section")
    db.execute(
        delete(TeacherSubject).where(
            TeacherSubject.institute_id == institute_id,
            TeacherSubject.user_id == user_id,
        )
    )
    for subject in subjects:
        db.add(
            TeacherSubject(institute_id=institute_id, user_id=user_id, subject_id=subject.id)
        )
    db.commit()
    return list_teacher_subjects(db, institute_id, user_id)
