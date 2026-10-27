from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Section, SectionSubject, Subject, TeacherSubjectAssignment
from app.roles import MANAGE_ROLES
from app.services.institutes import get_membership
from app.services.sections import (
    CLASS_ATTENDANCE_SUBJECT,
    can_take_attendance_today,
    teaching_staff_assigned_to_section,
)

CLASS_REGISTER_LABEL = "Class attendance"


def _subject_label(db: Session, subject_id: str) -> str:
    if not subject_id:
        return CLASS_REGISTER_LABEL
    subject = db.get(Subject, subject_id)
    return subject.name if subject else "Subject"


def markable_registers(db: Session, section: Section, user_id: str) -> list[dict]:
    member = get_membership(db, section.institute_id, user_id)
    if not member:
        return []
    out: list[dict] = []
    seen: set[str] = set()

    def add(subject_id: str) -> None:
        if subject_id in seen:
            return
        seen.add(subject_id)
        out.append({"subjectId": subject_id, "label": _subject_label(db, subject_id)})

    if member.role in MANAGE_ROLES or can_take_attendance_today(db, section, user_id):
        add(CLASS_ATTENDANCE_SUBJECT)

    if member.role in MANAGE_ROLES:
        for subject_id in db.scalars(
            select(SectionSubject.subject_id).where(SectionSubject.section_id == section.id)
        ):
            add(subject_id)
    elif teaching_staff_assigned_to_section(db, section.id, user_id):
        for subject_id in db.scalars(
            select(TeacherSubjectAssignment.subject_id).where(
                TeacherSubjectAssignment.section_id == section.id,
                TeacherSubjectAssignment.teacher_id == user_id,
            )
        ):
            add(subject_id)

    return out


def student_view_registers(db: Session, section_id: str) -> list[dict]:
    """All registers a student can view: homeroom plus every subject in this class."""
    from app.services.user_identity import enrich_rows  # noqa: PLC0415

    out: list[dict] = []
    seen: set[str] = set()

    def add(subject_id: str, label: str) -> None:
        if subject_id in seen:
            return
        seen.add(subject_id)
        out.append({"subjectId": subject_id, "label": label})

    add(CLASS_ATTENDANCE_SUBJECT, CLASS_REGISTER_LABEL)

    for subject_id in db.scalars(
        select(SectionSubject.subject_id).where(SectionSubject.section_id == section_id)
    ):
        subject = db.get(Subject, subject_id)
        name = subject.name if subject else "Subject"
        teacher_ids = list(
            db.scalars(
                select(TeacherSubjectAssignment.teacher_id).where(
                    TeacherSubjectAssignment.section_id == section_id,
                    TeacherSubjectAssignment.subject_id == subject_id,
                )
            )
        )
        if teacher_ids:
            teachers = enrich_rows([{"userId": tid} for tid in teacher_ids])
            teacher_names = ", ".join(
                (t.get("name") or t.get("email") or "Teacher") for t in teachers
            )
            add(subject_id, f"{name} — {teacher_names}")
        else:
            add(subject_id, name)

    return out
