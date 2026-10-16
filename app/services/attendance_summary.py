from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import AttendanceRecord, InstituteMember, Section, SectionMember
from app.roles import MANAGE_ROLES, STAFF_ROLES
from app.services.institutes import require_membership


def get_attendance_summary(
    db: Session, institute_id: str, user_id: str, day: date, campus_id: str | None
) -> dict:
    member = require_membership(db, institute_id, user_id)
    if member.role not in MANAGE_ROLES and member.role != "principal":
        raise PermissionError("Owner or principal role required")

    section_stmt = select(Section.id).where(Section.institute_id == institute_id)
    if campus_id:
        section_stmt = section_stmt.where(Section.branch_id == campus_id)
    section_ids = list(db.scalars(section_stmt))
    sections_total = len(section_ids)

    students_total = db.scalar(
        select(func.count(func.distinct(SectionMember.user_id)))
        .select_from(SectionMember)
        .join(Section, Section.id == SectionMember.section_id)
        .where(
            Section.institute_id == institute_id,
            SectionMember.member_type == "student",
            *([Section.branch_id == campus_id] if campus_id else []),
        )
    )

    if not section_ids:
        return {
            "studentsTotal": students_total or 0,
            "present": 0,
            "absent": 0,
            "late": 0,
            "staffTotal": 0,
            "staffPresent": 0,
            "sectionsTotal": 0,
            "sectionsPending": 0,
        }

    records = db.execute(
        select(AttendanceRecord.status, func.count())
        .where(
            AttendanceRecord.section_id.in_(section_ids),
            AttendanceRecord.attendance_date == day,
        )
        .group_by(AttendanceRecord.status)
    ).all()
    counts = {status: count for status, count in records}
    present = counts.get("present", 0)
    absent = counts.get("absent", 0)
    late = counts.get("late", 0)

    marked_sections = db.scalar(
        select(func.count(func.distinct(AttendanceRecord.section_id)))
        .where(
            AttendanceRecord.section_id.in_(section_ids),
            AttendanceRecord.attendance_date == day,
        )
    )

    staff_total = db.scalar(
        select(func.count())
        .select_from(InstituteMember)
        .where(InstituteMember.institute_id == institute_id, InstituteMember.role.in_(STAFF_ROLES))
    )

    return {
        "studentsTotal": students_total or 0,
        "present": present,
        "absent": absent,
        "late": late,
        "staffTotal": staff_total or 0,
        "staffPresent": staff_total or 0,
        "sectionsTotal": sections_total,
        "sectionsPending": max(sections_total - int(marked_sections or 0), 0),
    }
