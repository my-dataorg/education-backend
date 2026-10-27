from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Section, SectionAttendanceDay
from app.roles import MANAGE_ROLES
from app.services.institutes import get_membership


def day_states_for_range(
    db: Session,
    section_id: str,
    start: date,
    end: date,
    *,
    subject_id: str = "",
) -> dict[date, SectionAttendanceDay]:
    rows = list(
        db.scalars(
            select(SectionAttendanceDay).where(
                SectionAttendanceDay.section_id == section_id,
                SectionAttendanceDay.subject_id == subject_id,
                SectionAttendanceDay.attendance_date >= start,
                SectionAttendanceDay.attendance_date <= end,
            )
        )
    )
    return {row.attendance_date: row for row in rows}


def can_view_attendance_for_date(
    db: Session, section: Section, day_row: SectionAttendanceDay | None, user_id: str
) -> bool:
    if day_row is None or day_row.publish_state == "submitted":
        return True
    if day_row.marked_by == user_id:
        return True
    member = get_membership(db, section.institute_id, user_id)
    return bool(member and member.role in MANAGE_ROLES)


def upsert_attendance_day(
    db: Session,
    section_id: str,
    attendance_date: date,
    user_id: str,
    publish_state: str,
    *,
    subject_id: str = "",
) -> None:
    state = "submitted" if publish_state == "submitted" else "draft"
    row = db.scalar(
        select(SectionAttendanceDay).where(
            SectionAttendanceDay.section_id == section_id,
            SectionAttendanceDay.attendance_date == attendance_date,
            SectionAttendanceDay.subject_id == subject_id,
        )
    )
    if row:
        row.publish_state = state
        row.marked_by = user_id
    else:
        db.add(
            SectionAttendanceDay(
                section_id=section_id,
                attendance_date=attendance_date,
                subject_id=subject_id,
                publish_state=state,
                marked_by=user_id,
            )
        )
