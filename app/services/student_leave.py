from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import StudentLeaveRequest
from app.services.sections import require_section_teacher
from app.services.user_identity import enrich_rows


def list_section_leave_requests(
    db: Session,
    section_id: str,
    user_id: str,
    *,
    status: str | None = None,
) -> list[dict]:
    require_section_teacher(db, section_id, user_id)
    stmt = select(StudentLeaveRequest).where(StudentLeaveRequest.section_id == section_id)
    if status:
        stmt = stmt.where(StudentLeaveRequest.status == status)
    rows = list(db.scalars(stmt.order_by(StudentLeaveRequest.created_at.desc())))
    if not rows:
        return []
    student_ids = {row.student_id for row in rows}
    names = {
        item["userId"]: item.get("displayName") or item.get("username") or item["userId"]
        for item in enrich_rows([{"userId": sid} for sid in student_ids])
    }
    return [
        {
            "id": row.id,
            "studentId": row.student_id,
            "studentName": names.get(row.student_id, row.student_id),
            "startDate": row.start_date.isoformat(),
            "endDate": row.end_date.isoformat(),
            "reason": row.reason,
            "status": row.status,
            "createdAt": row.created_at.isoformat() if row.created_at else None,
        }
        for row in rows
    ]


def list_student_leave_in_range(
    db: Session,
    section_id: str,
    student_id: str,
    user_id: str,
    start: date,
    end: date,
) -> list[dict]:
    require_section_teacher(db, section_id, user_id)
    rows = list(
        db.scalars(
            select(StudentLeaveRequest).where(
                StudentLeaveRequest.section_id == section_id,
                StudentLeaveRequest.student_id == student_id,
                StudentLeaveRequest.start_date <= end,
                StudentLeaveRequest.end_date >= start,
            )
        )
    )
    return [
        {
            "id": row.id,
            "startDate": row.start_date.isoformat(),
            "endDate": row.end_date.isoformat(),
            "reason": row.reason,
            "status": row.status,
        }
        for row in rows
    ]


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
