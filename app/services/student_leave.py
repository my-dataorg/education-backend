from datetime import date, timedelta

from sqlalchemy.orm import Session

from app.services.leave_requests import leave_rows_for_student_in_range, list_section_leave_for_teacher
from app.services.sections import require_section_student, require_section_teacher


def list_section_leave_requests(
    db: Session,
    section_id: str,
    user_id: str,
    *,
    status: str | None = None,
) -> list[dict]:
    require_section_teacher(db, section_id, user_id)
    return list_section_leave_for_teacher(db, section_id, user_id, status)


def list_student_leave_in_range(
    db: Session,
    section_id: str,
    student_id: str,
    user_id: str,
    start: date,
    end: date,
) -> list[dict]:
    if student_id == user_id:
        require_section_student(db, section_id, user_id)
    else:
        require_section_teacher(db, section_id, user_id)
    return leave_rows_for_student_in_range(db, section_id, student_id, start, end)


def leave_dates_in_month(leave_rows: list[dict], year: int, month: int) -> dict[str, str]:
    """Map ISO date -> leave status for days inside the month (month 1–12)."""
    month_start = date(year, month, 1)
    month_end = date(year + 1, 1, 1) - timedelta(days=1) if month == 12 else date(year, month + 1, 1) - timedelta(days=1)
    out: dict[str, str] = {}
    for row in leave_rows:
        start = date.fromisoformat(row["startDate"])
        end = date.fromisoformat(row["endDate"])
        cur = max(start, month_start)
        last = min(end, month_end)
        while cur <= last:
            out[cur.isoformat()] = row["status"]
            cur += timedelta(days=1)
    return out
