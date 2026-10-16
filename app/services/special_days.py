from datetime import date

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models import (
    AcademicYear,
    ScheduleSettings,
    ScheduleSpecialDay,
    Section,
    SpecialDayActivity,
    SpecialDayActivitySection,
    SpecialDayActivityTeacher,
)
from app.services.schedule import _build_special_days


def _day_item(db: Session, day: ScheduleSpecialDay) -> dict:
    section_ids: set[str] = set()
    teacher_ids: set[str] = set()
    activities = db.scalars(
        select(SpecialDayActivity)
        .where(SpecialDayActivity.special_day_id == day.id)
        .order_by(SpecialDayActivity.position)
    )
    for activity in activities:
        section_ids.update(
            db.scalars(
                select(SpecialDayActivitySection.section_id).where(
                    SpecialDayActivitySection.special_activity_id == activity.id
                )
            )
        )
        teacher_ids.update(
            db.scalars(
                select(SpecialDayActivityTeacher.teacher_id).where(
                    SpecialDayActivityTeacher.special_activity_id == activity.id
                )
            )
        )
    return {
        "specialDayId": day.id,
        "date": day.special_date,
        "name": day.label,
        "sections": sorted(section_ids),
        "teacherIds": sorted(teacher_ids),
        "replacesRegularSchedule": day.replace_regular,
    }


def list_special_days(
    db: Session,
    institute_id: str,
    *,
    year: str = "current",
    campus_id: str | None = None,
) -> dict:
    start: date | None = None
    end: date | None = None
    if year == "current":
        active = db.scalar(
            select(AcademicYear)
            .where(AcademicYear.institute_id == institute_id, AcademicYear.is_active.is_(True))
            .order_by(AcademicYear.start_date.desc())
        )
        if active:
            start = active.start_date
            end = active.end_date

    stmt = (
        select(ScheduleSpecialDay)
        .where(ScheduleSpecialDay.institute_id == institute_id)
        .order_by(ScheduleSpecialDay.special_date)
    )
    if start and end:
        stmt = stmt.where(
            ScheduleSpecialDay.special_date >= start,
            ScheduleSpecialDay.special_date <= end,
        )
    days = list(db.scalars(stmt))
    items = []
    for day in days:
        item = _day_item(db, day)
        if campus_id:
            sections = list(
                db.scalars(
                    select(Section).where(
                        Section.id.in_(item["sections"]),
                        Section.institute_id == institute_id,
                    )
                )
            )
            if not any(s.branch_id == campus_id or s.branch_id is None for s in sections):
                continue
        items.append(item)
    return {"items": items}


def create_special_day(db: Session, institute_id: str, body) -> dict:
    settings = db.get(ScheduleSettings, institute_id)
    if not settings:
        settings = ScheduleSettings(institute_id=institute_id)
        db.add(settings)
        db.flush()
    sections = {
        section.id: section
        for section in db.scalars(select(Section).where(Section.institute_id == institute_id))
    }
    built = _build_special_days(
        db,
        institute_id,
        [body],
        sections,
        settings.school_start,
        settings.school_end,
    )
    if not built:
        raise ValueError("Special day is required")
    special_day, activities = built[0]
    existing = db.scalar(
        select(ScheduleSpecialDay).where(
            ScheduleSpecialDay.institute_id == institute_id,
            ScheduleSpecialDay.special_date == special_day.special_date,
        )
    )
    if existing:
        raise ValueError("A special day already exists for this date")
    db.add(special_day)
    for activity, section_ids, teacher_ids in activities:
        db.add(activity)
        for section_id in section_ids:
            db.add(
                SpecialDayActivitySection(
                    special_activity_id=activity.id,
                    section_id=section_id,
                )
            )
        for teacher_id in teacher_ids:
            db.add(
                SpecialDayActivityTeacher(
                    special_activity_id=activity.id,
                    teacher_id=teacher_id,
                )
            )
    db.commit()
    return _day_item(db, special_day)


def delete_special_day(db: Session, institute_id: str, special_day_id: str) -> None:
    day = db.scalar(
        select(ScheduleSpecialDay).where(
            ScheduleSpecialDay.id == special_day_id,
            ScheduleSpecialDay.institute_id == institute_id,
        )
    )
    if not day:
        raise ValueError("Special day not found")
    activity_ids = select(SpecialDayActivity.id).where(
        SpecialDayActivity.special_day_id == day.id
    )
    db.execute(
        delete(SpecialDayActivitySection).where(
            SpecialDayActivitySection.special_activity_id.in_(activity_ids)
        )
    )
    db.execute(
        delete(SpecialDayActivityTeacher).where(
            SpecialDayActivityTeacher.special_activity_id.in_(activity_ids)
        )
    )
    db.execute(delete(SpecialDayActivity).where(SpecialDayActivity.special_day_id == day.id))
    db.delete(day)
    db.commit()
