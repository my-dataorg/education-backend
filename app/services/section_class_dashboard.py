"""Class-scoped snapshot for the section Overview tab (teachers)."""

from __future__ import annotations

import re
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Assignment, AttendanceRecord, InstituteCalendarEvent, InstitutePost, InstituteRoleSettings, SectionMember
from app.services.attendance_day import can_view_attendance_for_date, day_states_for_range
from app.services.notices import event_visible_to_user, parse_id_list, post_to_dict, post_visible_to_user
from app.services.institutes import get_membership
from app.services.sections import require_section_teacher
from app.services.user_identity import enrich_rows

_AWARD_RE = re.compile(r"\b(award|recognition|achievement|felicitation|merit)\b", re.I)


def _absence_alert_days(db: Session, institute_id: str) -> int:
    row = db.get(InstituteRoleSettings, institute_id)
    if row and getattr(row, "absence_alert_days", None):
        return max(1, min(int(row.absence_alert_days), 30))
    return 3


def _targets_section(section_id: str, target_section_ids: str) -> bool:
    return section_id in parse_id_list(target_section_ids)


def _consecutive_absent_days(records: dict[date, str], today: date) -> int:
    streak = 0
    day = today
    for _ in range(90):
        status = records.get(day)
        if status is None:
            day -= timedelta(days=1)
            continue
        if status == "absent":
            streak += 1
            day -= timedelta(days=1)
        else:
            break
    return streak


def get_section_class_dashboard(db: Session, section_id: str, user_id: str) -> dict:
    section = require_section_teacher(db, section_id, user_id)
    institute_id = section.institute_id
    today = date.today()
    week_end = today + timedelta(days=7)
    threshold = _absence_alert_days(db, institute_id)

    students = list(
        db.scalars(
            select(SectionMember).where(
                SectionMember.section_id == section_id,
                SectionMember.member_type == "student",
            )
        )
    )
    student_ids = [s.user_id for s in students]

    today_day = day_states_for_range(db, section_id, today, today).get(today)
    if not can_view_attendance_for_date(db, section, today_day, user_id):
        today_rows = []
    else:
        today_rows = list(
            db.scalars(
                select(AttendanceRecord).where(
                    AttendanceRecord.section_id == section_id,
                    AttendanceRecord.attendance_date == today,
                )
            )
        )
    by_student_today = {row.student_id: row.status for row in today_rows}
    if today_day and can_view_attendance_for_date(db, section, today_day, user_id):
        today_publish_state = today_day.publish_state
    elif today_rows:
        today_publish_state = "submitted"
    else:
        today_publish_state = None
    counts = {"present": 0, "absent": 0, "late": 0, "excused": 0, "unmarked": 0}
    today_students = []
    for student in students:
        status = by_student_today.get(student.user_id)
        if not status:
            counts["unmarked"] += 1
        else:
            counts[status] = counts.get(status, 0) + 1
    enriched = {row["userId"]: row for row in enrich_rows([{"userId": s.user_id} for s in students])}
    for student in students:
        status = by_student_today.get(student.user_id)
        if status:
            info = enriched.get(student.user_id, {})
            today_students.append(
                {
                    "userId": student.user_id,
                    "displayName": info.get("displayName") or info.get("username"),
                    "status": status,
                }
            )

    lookback_start = today - timedelta(days=90)
    history = list(
        db.scalars(
            select(AttendanceRecord).where(
                AttendanceRecord.section_id == section_id,
                AttendanceRecord.attendance_date >= lookback_start,
                AttendanceRecord.attendance_date <= today,
            )
        )
    )
    by_student: dict[str, dict[date, str]] = {sid: {} for sid in student_ids}
    for row in history:
        by_student.setdefault(row.student_id, {})[row.attendance_date] = row.status

    prolonged = []
    for student in students:
        streak = _consecutive_absent_days(by_student.get(student.user_id, {}), today)
        if streak >= threshold:
            info = enriched.get(student.user_id, {})
            prolonged.append(
                {
                    "userId": student.user_id,
                    "displayName": info.get("displayName") or info.get("username"),
                    "consecutiveAbsentDays": streak,
                }
            )
    prolonged.sort(key=lambda row: row["consecutiveAbsentDays"], reverse=True)

    assignments = list(
        db.scalars(
            select(Assignment).where(
                Assignment.section_id == section_id,
                Assignment.assignment_type == "test",
                Assignment.due_date.is_not(None),
                Assignment.due_date >= today,
                Assignment.due_date <= week_end,
            ).order_by(Assignment.due_date)
        )
    )
    upcoming_exams = [
        {
            "id": a.id,
            "title": a.title,
            "dueDate": a.due_date.isoformat() if a.due_date else None,
            "assignmentType": a.assignment_type,
        }
        for a in assignments
    ]

    membership = get_membership(db, institute_id, user_id)
    role = membership.role if membership else "teacher"

    posts = db.scalars(
        select(InstitutePost)
        .where(InstitutePost.institute_id == institute_id)
        .order_by(InstitutePost.created_at.desc())
        .limit(100)
    )
    class_notices = []
    awards = []
    for post in posts:
        if not post_visible_to_user(db, post, user_id, role):
            continue
        if not _targets_section(section_id, post.target_section_ids):
            continue
        item = post_to_dict(post)
        class_notices.append(item)
        text = f"{post.title} {post.body}"
        if _AWARD_RE.search(text):
            awards.append(item)

    events = db.scalars(
        select(InstituteCalendarEvent)
        .where(
            InstituteCalendarEvent.institute_id == institute_id,
            InstituteCalendarEvent.event_date >= today,
            InstituteCalendarEvent.event_date <= week_end,
        )
        .order_by(InstituteCalendarEvent.event_date)
    )
    class_events = []
    for event in events:
        if not event_visible_to_user(db, event, user_id, role):
            continue
        if not _targets_section(section_id, event.target_section_ids):
            continue
        class_events.append(
            {
                "id": event.id,
                "title": event.title,
                "description": event.description,
                "eventDate": event.event_date.isoformat(),
            }
        )

    return {
        "absenceAlertDays": threshold,
        "todayAttendance": {
            "date": today.isoformat(),
            "marked": len(today_rows),
            "totalStudents": len(students),
            "counts": counts,
            "students": today_students,
            "publishState": today_publish_state,
        },
        "prolongedAbsence": prolonged,
        "upcomingExams": upcoming_exams,
        "notices": class_notices[:8],
        "awards": awards[:6],
        "events": class_events[:8],
    }
