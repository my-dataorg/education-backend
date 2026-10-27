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

# Lunch and break are on the timetable but do not need a roll call.
_ATTENDANCE_NAME_BLOCKLIST = ("lunch", "break")


def _subject_label(db: Session, subject_id: str) -> str:
    if not subject_id:
        return CLASS_REGISTER_LABEL
    subject = db.get(Subject, subject_id)
    return subject.name if subject else "Subject"


def subject_eligible_for_attendance(subject: Subject | None) -> bool:
    if not subject or not subject.name.strip():
        return False
    name = subject.name.strip().lower()
    return not any(token in name for token in _ATTENDANCE_NAME_BLOCKLIST)


def _person_name(brief: dict) -> str:
    first = (brief.get("firstName") or "").strip()
    last = (brief.get("lastName") or "").strip()
    if first and last:
        return f"{first} {last}"
    if first or last:
        return first or last
    display = (brief.get("displayName") or "").strip()
    if display:
        return display
    return "Teacher"


def _register_label(db: Session, section_id: str, subject_id: str) -> str | None:
    subject = db.get(Subject, subject_id)
    if not subject_eligible_for_attendance(subject):
        return None
    name = subject.name if subject else "Subject"
    teacher_ids = list(
        db.scalars(
            select(TeacherSubjectAssignment.teacher_id).where(
                TeacherSubjectAssignment.section_id == section_id,
                TeacherSubjectAssignment.subject_id == subject_id,
            )
        )
    )
    if not teacher_ids:
        return name
    from app.services.user_identity import enrich_rows  # noqa: PLC0415

    teachers = enrich_rows([{"userId": tid} for tid in teacher_ids])
    teacher_names = ", ".join(_person_name(t) for t in teachers)
    return f"{name} ({teacher_names})"


def markable_registers(db: Session, section: Section, user_id: str) -> list[dict]:
    member = get_membership(db, section.institute_id, user_id)
    if not member:
        return []
    out: list[dict] = []
    seen: set[str] = set()

    def add(subject_id: str, label: str) -> None:
        if subject_id in seen:
            return
        seen.add(subject_id)
        out.append({"subjectId": subject_id, "label": label})

    if member.role in MANAGE_ROLES or can_take_attendance_today(db, section, user_id):
        add(CLASS_ATTENDANCE_SUBJECT, CLASS_REGISTER_LABEL)

    subject_ids: list[str] = []
    if member.role in MANAGE_ROLES:
        subject_ids = list(
            db.scalars(
                select(SectionSubject.subject_id).where(SectionSubject.section_id == section.id)
            )
        )
    elif teaching_staff_assigned_to_section(db, section.id, user_id):
        subject_ids = list(
            db.scalars(
                select(TeacherSubjectAssignment.subject_id).where(
                    TeacherSubjectAssignment.section_id == section.id,
                    TeacherSubjectAssignment.teacher_id == user_id,
                )
            )
        )

    for subject_id in subject_ids:
        label = _register_label(db, section.id, subject_id)
        if label:
            add(subject_id, label)

    return out


def student_view_registers(db: Session, section_id: str) -> list[dict]:
    """Homeroom plus class subjects and activities (not lunch or break)."""
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
        label = _register_label(db, section_id, subject_id)
        if label:
            add(subject_id, label)

    return out
