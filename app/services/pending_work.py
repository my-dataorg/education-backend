from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Assignment, Section, SectionMember, Subject, Submission
from app.services.institutes import require_membership
from app.services.sections import list_my_enrolled_sections

TEACHING_ROLES = frozenset({"teacher", "lecturer", "professor"})


def _section_label(class_name: str, name: str) -> str:
    parts = [p for p in (class_name.strip(), name.strip()) if p]
    return " ".join(parts) or "section"


def _deadline_copy(due: date | None) -> str:
    if due is None:
        return "No due date"
    if due < date.today():
        return f"Overdue {due.isoformat()}"
    return f"Due {due.isoformat()}"


def _enroll_item() -> dict:
    return {
        "kind": "enroll_in_section",
        "title": "You're not in a section yet",
        "detail": "Ask an admin to enroll you so you can see classes and assignments.",
        "href": None,
        "dueDate": None,
    }


def _sort_key(item: dict) -> tuple:
    due = item["_due"]
    if due is None:
        return (2, date.max, item["title"])
    if due < date.today():
        return (0, due, item["title"])
    return (1, due, item["title"])


def _finalize(items: list[dict]) -> list[dict]:
    items.sort(key=_sort_key)
    for item in items:
        item["dueDate"] = item.pop("_due")
    return items


def list_pending_work(db: Session, institute_id: str, user_id: str) -> list[dict]:
    member = require_membership(db, institute_id, user_id)
    sections = list_my_enrolled_sections(db, institute_id, user_id)

    if member.role == "student":
        if not sections:
            return [_enroll_item()]
        return _student_items(db, institute_id, user_id, sections)
    if member.role in TEACHING_ROLES:
        if not sections:
            return [_enroll_item()]
        return _teacher_items(db, institute_id, sections)
    return []


def _assignment_rows(db: Session, section_ids: list[str]):
    return db.execute(
        select(Assignment, Section, Subject.name)
        .join(Section, Section.id == Assignment.section_id)
        .outerjoin(Subject, Subject.id == Assignment.subject_id)
        .where(Assignment.section_id.in_(section_ids))
    ).all()


def _student_items(db: Session, institute_id: str, user_id: str, sections: list[dict]) -> list[dict]:
    section_ids = [s["id"] for s in sections]
    rows = _assignment_rows(db, section_ids)
    assignment_ids = [assignment.id for assignment, _, _ in rows]
    submitted = set(
        db.scalars(
            select(Submission.assignment_id).where(
                Submission.student_id == user_id,
                Submission.assignment_id.in_(assignment_ids),
            )
        ).all()
    ) if assignment_ids else set()

    items = []
    for assignment, section, subject_name in rows:
        if assignment.id in submitted:
            continue
        label = _section_label(section.class_name, section.name)
        parts = [_deadline_copy(assignment.due_date), label]
        if subject_name:
            parts.append(subject_name)
        items.append(
            {
                "kind": "submit_assignment",
                "title": f"Submit {assignment.title}",
                "detail": " · ".join(parts),
                "href": f"/institutes/{institute_id}/sections/{section.id}",
                "_due": assignment.due_date,
            }
        )
    return _finalize(items)


def _teacher_items(db: Session, institute_id: str, sections: list[dict]) -> list[dict]:
    section_ids = [s["id"] for s in sections]
    rows = _assignment_rows(db, section_ids)
    assignment_ids = [assignment.id for assignment, _, _ in rows]
    enrolled = dict(
        db.execute(
            select(SectionMember.section_id, func.count(func.distinct(SectionMember.user_id)))
            .where(
                SectionMember.section_id.in_(section_ids),
                SectionMember.member_type == "student",
            )
            .group_by(SectionMember.section_id)
        ).all()
    )
    submitted = dict(
        db.execute(
            select(Submission.assignment_id, func.count())
            .join(Assignment, Assignment.id == Submission.assignment_id)
            .join(
                SectionMember,
                (SectionMember.section_id == Assignment.section_id)
                & (SectionMember.user_id == Submission.student_id)
                & (SectionMember.member_type == "student"),
            )
            .where(Submission.assignment_id.in_(assignment_ids))
            .group_by(Submission.assignment_id)
        ).all()
    ) if assignment_ids else {}

    items = []
    for assignment, section, _subject_name in rows:
        student_count = enrolled.get(section.id, 0)
        missing = student_count - submitted.get(assignment.id, 0)
        if missing <= 0:
            continue
        label = _section_label(section.class_name, section.name)
        items.append(
            {
                "kind": "review_assignment",
                "title": f"{assignment.title} still has missing work",
                "detail": (
                    f"{_deadline_copy(assignment.due_date)} · {missing} of {student_count} "
                    f"students have not submitted · {label}"
                ),
                "href": f"/institutes/{institute_id}/sections/{section.id}",
                "_due": assignment.due_date,
            }
        )
    return _finalize(items)
