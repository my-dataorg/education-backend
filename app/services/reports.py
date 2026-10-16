import csv
import io
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import AttendanceRecord, InstituteMember, Section, SectionMember
from app.roles import MANAGE_ROLES
from app.services.institutes import require_membership


def _require_report_access(db: Session, institute_id: str, user_id: str) -> None:
    member = require_membership(db, institute_id, user_id)
    if member.role not in MANAGE_ROLES and member.role != "principal":
        raise PermissionError("Owner or principal role required")


def attendance_report_csv(
    db: Session, institute_id: str, user_id: str, month: date | None, campus_id: str | None
) -> str:
    _require_report_access(db, institute_id, user_id)
    ref = month or date.today()
    start = ref.replace(day=1)
    if ref.month == 12:
        end = date(ref.year + 1, 1, 1)
    else:
        end = date(ref.year, ref.month + 1, 1)

    section_stmt = select(Section).where(Section.institute_id == institute_id)
    if campus_id:
        section_stmt = section_stmt.where(Section.branch_id == campus_id)
    sections = list(db.scalars(section_stmt.order_by(Section.class_name, Section.name)))

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["class_name", "section_name", "present", "absent", "late", "working_days"])
    for section in sections:
        rows = db.execute(
            select(AttendanceRecord.status, func.count())
            .where(
                AttendanceRecord.section_id == section.id,
                AttendanceRecord.attendance_date >= start,
                AttendanceRecord.attendance_date < end,
            )
            .group_by(AttendanceRecord.status)
        ).all()
        counts = {status: count for status, count in rows}
        working_days = sum(counts.values())
        writer.writerow(
            [
                section.class_name,
                section.name,
                counts.get("present", 0),
                counts.get("absent", 0),
                counts.get("late", 0),
                working_days,
            ]
        )
    return buffer.getvalue()


def enrollment_report_csv(db: Session, institute_id: str, user_id: str, campus_id: str | None) -> str:
    _require_report_access(db, institute_id, user_id)
    stmt = (
        select(Section.class_name, Section.name, func.count(SectionMember.user_id))
        .join(SectionMember, SectionMember.section_id == Section.id)
        .where(Section.institute_id == institute_id, SectionMember.member_type == "student")
        .group_by(Section.id, Section.class_name, Section.name)
        .order_by(Section.class_name, Section.name)
    )
    if campus_id:
        stmt = stmt.where(Section.branch_id == campus_id)

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["class_name", "section_name", "student_count"])
    for class_name, section_name, count in db.execute(stmt):
        writer.writerow([class_name, section_name, count])
    writer.writerow(
        [
            "total_members",
            "",
            db.scalar(
                select(func.count())
                .select_from(InstituteMember)
                .where(InstituteMember.institute_id == institute_id, InstituteMember.role == "student")
            )
            or 0,
        ]
    )
    return buffer.getvalue()


def build_report(db: Session, institute_id: str, user_id: str, report_type: str, **kwargs) -> str:
    if report_type == "attendance":
        return attendance_report_csv(db, institute_id, user_id, kwargs.get("month"), kwargs.get("campus_id"))
    if report_type == "enrollment":
        return enrollment_report_csv(db, institute_id, user_id, kwargs.get("campus_id"))
    raise ValueError(f"Unknown report type: {report_type}")
