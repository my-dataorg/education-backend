from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Period, Section, SectionMember, Subject
from app.roles import STUDENT_ROLE
from app.services.institutes import require_membership
from app.services.sections import list_my_enrolled_sections

PERIOD_MINUTES = 60
WEEKDAYS = (
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
    "sunday",
)
EVERYDAY = "everyday"


class PeriodConflict(ValueError):
    pass


def _days(weekday: str) -> set[str]:
    tokens = [part.strip().lower() for part in weekday.split(",") if part.strip()]
    if EVERYDAY in tokens:
        return set(WEEKDAYS)
    return set(tokens)


def _normalize_weekdays(weekday: str) -> str:
    tokens = [part.strip().lower() for part in weekday.split(",") if part.strip()]
    if not tokens:
        raise ValueError("Choose Everyday or at least one day of the week")
    if EVERYDAY in tokens:
        if len(tokens) > 1:
            raise ValueError("Everyday cannot be combined with specific days")
        return EVERYDAY
    unknown = [day for day in tokens if day not in WEEKDAYS]
    if unknown:
        raise ValueError("Weekday must be everyday or days of the week")
    ordered = [day for day in WEEKDAYS if day in tokens]
    return ",".join(ordered)


def _minutes(start_time: str) -> int:
    hour, minute = start_time.split(":")
    return int(hour) * 60 + int(minute)


def _validate_slot(weekday: str, start_time: str) -> tuple[str, str]:
    day = _normalize_weekdays(weekday)
    parts = start_time.strip().split(":")
    if len(parts) < 2:
        raise ValueError("Start time must be HH:MM")
    hour, minute = int(parts[0]), int(parts[1])
    if hour < 0 or hour > 23 or minute < 0 or minute > 59:
        raise ValueError("Start time must be HH:MM")
    return day, f"{hour:02d}:{minute:02d}"


def _time_overlaps(a: str, b: str) -> bool:
    start_a = _minutes(a)
    start_b = _minutes(b)
    return start_a < start_b + PERIOD_MINUTES and start_b < start_a + PERIOD_MINUTES


def _slots_overlap(weekday_a: str, time_a: str, weekday_b: str, time_b: str) -> bool:
    return bool(_days(weekday_a) & _days(weekday_b)) and _time_overlaps(time_a, time_b)


def _semester(label: str) -> str:
    name = " ".join(label.split())
    if not name:
        raise ValueError("Semester is required, for example Summer 2026")
    if len(name) > 80:
        raise ValueError("Semester must be 80 characters or fewer")
    return name


def list_periods(db: Session, institute_id: str) -> list[Period]:
    return list(
        db.scalars(
            select(Period)
            .where(Period.institute_id == institute_id)
            .order_by(Period.weekday, Period.start_time)
        )
    )


def _end_clock(start_time: str, duration_minutes: int) -> str:
    total = _minutes(start_time) + duration_minutes
    return f"{(total // 60) % 24:02d}:{total % 60:02d}"


def list_my_classes_for_day(
    db: Session,
    institute_id: str,
    user_id: str,
    weekday: str | None = None,
) -> dict:
    member = require_membership(db, institute_id, user_id)
    day = (weekday or WEEKDAYS[date.today().weekday()]).strip().lower()
    if day not in WEEKDAYS:
        raise ValueError("Weekday must be a day of the week")

    enrolled_ids = set()
    if member.role == STUDENT_ROLE:
        enrolled_ids = {row["id"] for row in list_my_enrolled_sections(db, institute_id, user_id)}
    items = []
    for period in list_periods(db, institute_id):
        if day not in _days(period.weekday):
            continue
        taught_by_me = period.teacher_user_id == user_id
        student_in_section = member.role == STUDENT_ROLE and period.section_id in enrolled_ids
        if not taught_by_me and not student_in_section:
            continue
        row = period_row(db, period)
        duration = period.duration_minutes or PERIOD_MINUTES
        items.append(
            {
                "periodId": period.id,
                "sectionId": period.section_id,
                "className": row["className"],
                "sectionName": row["sectionName"],
                "subjectId": period.subject_id,
                "subjectName": row["subjectName"],
                "startTime": period.start_time,
                "endTime": _end_clock(period.start_time, duration),
                "durationMinutes": duration,
                "href": f"/institutes/{institute_id}/sections/{period.section_id}",
            }
        )
    items.sort(key=lambda item: item["startTime"])
    return {"weekday": day, "items": items}


def period_row(db: Session, period: Period) -> dict:
    section = db.get(Section, period.section_id)
    subject = db.get(Subject, period.subject_id)
    return {
        "id": period.id,
        "sectionId": period.section_id,
        "sectionName": section.name if section else "",
        "className": section.class_name if section else "",
        "subjectId": period.subject_id,
        "subjectName": subject.name if subject else "",
        "teacherUserId": period.teacher_user_id,
        "semester": period.semester,
        "weekday": period.weekday,
        "startTime": period.start_time,
        "durationMinutes": PERIOD_MINUTES,
    }


def create_period(
    db: Session,
    institute_id: str,
    section_id: str,
    subject_id: str,
    teacher_user_id: str,
    weekday: str,
    start_time: str,
    semester: str,
) -> Period:
    day, clock = _validate_slot(weekday, start_time)
    term = _semester(semester)
    section = db.get(Section, section_id)
    if not section or section.institute_id != institute_id:
        raise ValueError("Section not found")
    assigned = db.scalar(
        select(SectionMember).where(
            SectionMember.section_id == section_id,
            SectionMember.user_id == teacher_user_id,
            SectionMember.member_type == "teacher",
            SectionMember.subject_id == subject_id,
        )
    )
    if not assigned:
        raise ValueError("Teacher is not assigned that subject in this section")

    existing = list(
        db.scalars(select(Period).where(Period.institute_id == institute_id))
    )
    for other in existing:
        if other.semester != term:
            continue
        if not _slots_overlap(day, clock, other.weekday, other.start_time):
            continue
        if other.teacher_user_id == teacher_user_id:
            raise PeriodConflict("Teacher already has a class in that hour")
        if other.section_id == section_id:
            raise PeriodConflict("This section already has a class in that hour")

    row = Period(
        institute_id=institute_id,
        section_id=section_id,
        subject_id=subject_id,
        teacher_user_id=teacher_user_id,
        semester=term,
        weekday=day,
        start_time=clock,
        duration_minutes=PERIOD_MINUTES,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def delete_period(db: Session, institute_id: str, period_id: str) -> None:
    row = db.get(Period, period_id)
    if not row or row.institute_id != institute_id:
        raise ValueError("Period not found")
    db.delete(row)
    db.commit()
