from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import (
    InstituteMember,
    Section,
    SectionMember,
    SectionSubject,
    Subject,
    TeacherSubjectAssignment,
)
from app.services.institutes import get_membership


def require_owner(db: Session, institute_id: str, user_id: str) -> InstituteMember:
    member = get_membership(db, institute_id, user_id)
    if not member or member.role != "owner":
        raise PermissionError("Owner role required")
    return member


def list_subjects(db: Session, institute_id: str) -> list[Subject]:
    return list(
        db.scalars(select(Subject).where(Subject.institute_id == institute_id).order_by(Subject.name))
    )


def create_subject(db: Session, institute_id: str, name: str) -> Subject:
    subject = Subject(institute_id=institute_id, name=name.strip())
    db.add(subject)
    try:
        db.commit()
    except IntegrityError as error:
        db.rollback()
        raise ValueError("Subject already exists") from error
    db.refresh(subject)
    return subject


def delete_subject(db: Session, institute_id: str, subject_id: str) -> None:
    subject = db.scalar(
        select(Subject).where(Subject.id == subject_id, Subject.institute_id == institute_id)
    )
    if not subject:
        raise ValueError("Subject not found")
    db.execute(delete(TeacherSubjectAssignment).where(TeacherSubjectAssignment.subject_id == subject_id))
    db.execute(delete(SectionSubject).where(SectionSubject.subject_id == subject_id))
    db.delete(subject)
    db.commit()


def get_section(db: Session, section_id: str) -> Section:
    section = db.get(Section, section_id)
    if not section:
        raise ValueError("Section not found")
    return section


def list_section_subjects(db: Session, section_id: str) -> list[dict]:
    rows = db.execute(
        select(Subject, SectionSubject)
        .join(SectionSubject, SectionSubject.subject_id == Subject.id)
        .where(SectionSubject.section_id == section_id)
        .order_by(Subject.name)
    )
    result = []
    for subject, _ in rows:
        teachers = db.scalars(
            select(TeacherSubjectAssignment.teacher_id).where(
                TeacherSubjectAssignment.section_id == section_id,
                TeacherSubjectAssignment.subject_id == subject.id,
            )
        )
        result.append({"id": subject.id, "name": subject.name, "teachers": list(teachers)})
    return result


def link_subject(db: Session, section_id: str, subject_id: str) -> Subject:
    section = get_section(db, section_id)
    subject = db.get(Subject, subject_id)
    if not subject or subject.institute_id != section.institute_id:
        raise ValueError("Subject not found")
    existing = db.scalar(
        select(SectionSubject).where(
            SectionSubject.section_id == section_id, SectionSubject.subject_id == subject_id
        )
    )
    if not existing:
        db.add(SectionSubject(section_id=section_id, subject_id=subject_id))
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
    return subject


def unlink_subject(db: Session, section_id: str, subject_id: str) -> None:
    db.execute(
        delete(SectionSubject).where(
            SectionSubject.section_id == section_id, SectionSubject.subject_id == subject_id
        )
    )
    db.execute(
        delete(TeacherSubjectAssignment).where(
            TeacherSubjectAssignment.section_id == section_id,
            TeacherSubjectAssignment.subject_id == subject_id,
        )
    )
    db.commit()


def assign_teacher(db: Session, section_id: str, subject_id: str, teacher_id: str) -> None:
    section = get_section(db, section_id)
    linked = db.scalar(
        select(SectionSubject).where(
            SectionSubject.section_id == section_id, SectionSubject.subject_id == subject_id
        )
    )
    teacher = db.scalar(
        select(SectionMember).where(
            SectionMember.section_id == section_id,
            SectionMember.user_id == teacher_id,
            SectionMember.member_type == "teacher",
        )
    )
    membership = get_membership(db, section.institute_id, teacher_id)
    if not linked or not teacher or not membership:
        raise ValueError("Teacher or subject is not assigned to this section")
    existing = db.scalar(
        select(TeacherSubjectAssignment).where(
            TeacherSubjectAssignment.section_id == section_id,
            TeacherSubjectAssignment.subject_id == subject_id,
            TeacherSubjectAssignment.teacher_id == teacher_id,
        )
    )
    if not existing:
        db.add(
            TeacherSubjectAssignment(
                section_id=section_id, subject_id=subject_id, teacher_id=teacher_id
            )
        )
        try:
            db.commit()
        except IntegrityError:
            db.rollback()


def unassign_teacher(db: Session, section_id: str, subject_id: str, teacher_id: str) -> None:
    db.execute(
        delete(TeacherSubjectAssignment).where(
            TeacherSubjectAssignment.section_id == section_id,
            TeacherSubjectAssignment.subject_id == subject_id,
            TeacherSubjectAssignment.teacher_id == teacher_id,
        )
    )
    db.commit()
