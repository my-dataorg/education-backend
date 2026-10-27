from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AttendanceRecord, Section, SectionMember
from app.services.attendance_day import (
    can_view_attendance_for_date,
    day_states_for_range,
    upsert_attendance_day,
)
from app.services.academic_years import get_active_academic_year_bounds
from app.services.attendance_registers import markable_registers
from app.services.institute_time import institute_local_date
from app.services.sections import (
    CLASS_ATTENDANCE_SUBJECT,
    attendance_mark_permissions,
    assert_can_mark_attendance,
    can_mark_attendance_register,
    require_section_attendance_staff,
)
from app.services.user_identity import enrich_rows

MAX_SHEET_DAYS = 366
SUMMARY_PERIODS = frozenset({"week", "month", "year", "academic_year"})


def _count_range(status_map: dict[str, str], start: date, end: date) -> dict[str, int]:
    counts = {k: 0 for k in ("present", "absent", "late", "excused", "unmarked")}
    today = date.today()
    end_eff = min(end, today)
    if start > end_eff:
        return counts
    cur = start
    while cur <= end_eff:
        status = status_map.get(cur.isoformat())
        if not status or status == "absent":
            counts["absent"] += 1
        elif status in counts:
            counts[status] += 1
        cur += timedelta(days=1)
    return counts


def _resolve_summary_range(
    db: Session,
    section_id: str,
    period: str,
    grid_end: date,
) -> tuple[date, date, str]:
    today = date.today()
    end_eff = min(grid_end, today)
    if period == "week":
        return end_eff - timedelta(days=6), end_eff, "Last 7 days"
    if period == "month":
        return end_eff - timedelta(days=29), end_eff, "Last 30 days"
    if period == "year":
        return end_eff - timedelta(days=364), end_eff, "Last 365 days"
    section = db.get(Section, section_id)
    if not section:
        raise ValueError("Section not found")
    start, end, label = get_active_academic_year_bounds(db, section.institute_id)
    return start, min(end, today), f"Academic year {label}"


def get_section_attendance_sheet(
    db: Session,
    section_id: str,
    user_id: str,
    *,
    days: int = 7,
    end_date: date | None = None,
    summary_period: str = "academic_year",
    subject_id: str = CLASS_ATTENDANCE_SUBJECT,
) -> dict:
    section = require_section_attendance_staff(db, section_id, user_id)
    days = max(1, min(days, MAX_SHEET_DAYS))
    period = summary_period if summary_period in SUMMARY_PERIODS else "academic_year"

    institute_today = institute_local_date(db, section.institute_id)
    end = end_date or institute_today
    grid_start = end - timedelta(days=days - 1)
    date_list = [grid_start + timedelta(days=i) for i in range(days)]

    summary_start, summary_end, summary_label = _resolve_summary_range(
        db, section_id, period, end
    )
    query_start = min(grid_start, summary_start)
    query_end = max(end, summary_end)

    students = list(
        db.scalars(
            select(SectionMember).where(
                SectionMember.section_id == section_id,
                SectionMember.member_type == "student",
            )
        )
    )
    student_rows = enrich_rows([{"userId": s.user_id} for s in students])

    day_states = day_states_for_range(
        db, section_id, query_start, query_end, subject_id=subject_id
    )
    records = list(
        db.scalars(
            select(AttendanceRecord).where(
                AttendanceRecord.section_id == section_id,
                AttendanceRecord.subject_id == subject_id,
                AttendanceRecord.attendance_date >= query_start,
                AttendanceRecord.attendance_date <= query_end,
            )
        )
    )
    status_by_student: dict[str, dict[str, str]] = {}
    publish_state_by_date: dict[str, str] = {}
    for row in records:
        day_row = day_states.get(row.attendance_date)
        if not can_view_attendance_for_date(db, section, day_row, user_id):
            continue
        iso = row.attendance_date.isoformat()
        status_by_student.setdefault(row.student_id, {})[iso] = row.status
        if day_row:
            publish_state_by_date[iso] = day_row.publish_state

    for d in date_list:
        dr = day_states.get(d)
        if dr and can_view_attendance_for_date(db, section, dr, user_id):
            publish_state_by_date[d.isoformat()] = dr.publish_state

    totals_by_student = {
        s.user_id: _count_range(
            status_by_student.get(s.user_id, {}), summary_start, summary_end
        )
        for s in students
    }

    registers = markable_registers(db, section, user_id)
    can_mark_today = can_mark_attendance_register(
        db, section, user_id, subject_id, institute_today
    )
    perms = attendance_mark_permissions(db, section, user_id)
    if subject_id != CLASS_ATTENDANCE_SUBJECT:
        perms = {**perms, "canTakeAttendanceToday": can_mark_today}

    return {
        "startDate": grid_start.isoformat(),
        "endDate": end.isoformat(),
        "instituteToday": institute_today.isoformat(),
        "subjectId": subject_id,
        "registers": registers,
        "dates": [d.isoformat() for d in date_list],
        "students": student_rows,
        "statusByStudent": status_by_student,
        "totalsByStudent": totals_by_student,
        "totalsLabel": summary_label,
        "totalsStartDate": summary_start.isoformat(),
        "totalsEndDate": summary_end.isoformat(),
        "publishStateByDate": publish_state_by_date,
        **perms,
    }


def save_present_only_attendance(
    db: Session,
    section_id: str,
    user_id: str,
    attendance_date: date,
    present_student_ids: list[str],
    excused_student_ids: list[str] | None = None,
    publish_state: str = "submitted",
    *,
    subject_id: str = CLASS_ATTENDANCE_SUBJECT,
) -> None:
    section = require_section_attendance_staff(db, section_id, user_id)
    assert_can_mark_attendance(db, section, user_id, attendance_date, subject_id=subject_id)
    enrolled = set(
        db.scalars(
            select(SectionMember.user_id).where(
                SectionMember.section_id == section_id,
                SectionMember.member_type == "student",
            )
        )
    )
    present = {sid for sid in present_student_ids if sid in enrolled}
    excused = {sid for sid in (excused_student_ids or []) if sid in enrolled} - present

    for sid in enrolled:
        if sid in present:
            status = "present"
        elif sid in excused:
            status = "excused"
        else:
            status = "absent"
        existing = db.scalar(
            select(AttendanceRecord).where(
                AttendanceRecord.section_id == section_id,
                AttendanceRecord.student_id == sid,
                AttendanceRecord.attendance_date == attendance_date,
                AttendanceRecord.subject_id == subject_id,
            )
        )
        if existing:
            existing.status = status
            existing.marked_by = user_id
        else:
            db.add(
                AttendanceRecord(
                    section_id=section_id,
                    student_id=sid,
                    attendance_date=attendance_date,
                    subject_id=subject_id,
                    status=status,
                    marked_by=user_id,
                )
            )
    upsert_attendance_day(
        db, section_id, attendance_date, user_id, publish_state, subject_id=subject_id
    )
    db.commit()
