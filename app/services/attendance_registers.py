from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Section, SectionAttendanceDay, SectionSubject, Subject, TeacherSubjectAssignment
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
    subject_ids = db.scalars(
        select(SectionAttendanceDay.subject_id)
        .where(
            SectionAttendanceDay.section_id == section_id,
            SectionAttendanceDay.publish_state == "submitted",
        )
        .distinct()
    )
    out = []
    for subject_id in subject_ids:
        out.append({"subjectId": subject_id, "label": _subject_label(db, subject_id)})
    if not out:
        out.append({"subjectId": CLASS_ATTENDANCE_SUBJECT, "label": CLASS_REGISTER_LABEL})
    return sorted(out, key=lambda row: (row["subjectId"] != "", row["label"]))
