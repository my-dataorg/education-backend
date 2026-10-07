from datetime import time

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import (
    Activity,
    InstituteMember,
    ScheduleSettings,
    ScheduleSlot,
    ScheduleSpecialDay,
    Section,
    SectionMember,
    SectionSubject,
    SpecialDayActivity,
    SpecialDayActivitySection,
    SpecialDayActivityTeacher,
    Subject,
    TimetableEntry,
)
from app.services.institutes import get_membership
from app.roles import MANAGE_ROLES, STAFF_ROLES, TEACHING_STAFF_ROLES


def get_schedule(db: Session, institute_id: str, user_id: str | None = None) -> dict:
    settings = db.get(ScheduleSettings, institute_id)
    if not settings:
        settings = ScheduleSettings(institute_id=institute_id)
        db.add(settings)
        try:
            db.commit()
            db.refresh(settings)
        except IntegrityError:
            db.rollback()
            settings = db.get(ScheduleSettings, institute_id)
            if not settings:
                raise
    slots = list(
        db.scalars(
            select(ScheduleSlot)
            .where(ScheduleSlot.institute_id == institute_id)
            .order_by(ScheduleSlot.position)
        )
    )
    entries_query = select(TimetableEntry).where(TimetableEntry.institute_id == institute_id)
    if user_id:
        member = get_membership(db, institute_id, user_id)
        if member and member.role not in MANAGE_ROLES | STAFF_ROLES:
            section_ids = select(SectionMember.section_id).where(SectionMember.user_id == user_id)
            entries_query = entries_query.where(TimetableEntry.section_id.in_(section_ids))
    entries = list(db.scalars(entries_query))
    special_days = list(
        db.scalars(
            select(ScheduleSpecialDay)
            .where(ScheduleSpecialDay.institute_id == institute_id)
            .order_by(ScheduleSpecialDay.special_date)
        )
    )
    visible_sections = None
    if user_id and member and member.role not in MANAGE_ROLES | STAFF_ROLES:
        visible_sections = set(
            db.scalars(
                select(SectionMember.section_id).where(SectionMember.user_id == user_id)
            )
        )
    return _output(settings, slots, entries, special_days, visible_sections, db)


def replace_schedule(db: Session, institute_id: str, body) -> dict:
    settings = db.scalar(
        select(ScheduleSettings)
        .where(ScheduleSettings.institute_id == institute_id)
        .with_for_update()
    )
    if not settings:
        settings = ScheduleSettings(institute_id=institute_id)
        db.add(settings)
        db.flush()
    if body.revision != settings.revision:
        raise RuntimeError("Schedule changed. Reload it and try again.")

    start = _parse_time(body.settings.schoolStart)
    end = _parse_time(body.settings.schoolEnd)
    if start >= end:
        raise ValueError("School end time must be after school start time")
    slots = []
    slot_ids = set()
    positions = set()
    for slot_input in body.slots:
        if not slot_input.label.strip():
            raise ValueError("Schedule slot label is required")
        slot_start = _parse_time(slot_input.start)
        slot_end = _parse_time(slot_input.end)
        if slot_start >= slot_end or slot_start < start or slot_end > end:
            raise ValueError("Every schedule slot must fit within school hours")
        if (
            slot_input.kind in {"break", "activity"}
            and slot_input.dayOfWeek is not None
            and slot_input.dayOfWeek not in body.settings.weekdays
        ):
            raise ValueError("Break day must be enabled for this schedule")
        if slot_input.kind == "activity":
            if not slot_input.activityId:
                raise ValueError("Activity slots require an activity")
            activity = db.get(Activity, slot_input.activityId)
            if not activity or activity.institute_id != institute_id:
                raise ValueError("Activity does not belong to this institute")
        elif slot_input.activityId:
            raise ValueError("Only activity slots can reference an activity")
        if slot_input.position in positions:
            raise ValueError("Schedule slot positions must be unique")
        positions.add(slot_input.position)
        slot_id = slot_input.id or _new_id()
        if slot_id in slot_ids:
            raise ValueError("Schedule slot IDs must be unique")
        slot_ids.add(slot_id)
        slots.append(
            ScheduleSlot(
                id=slot_id,
                institute_id=institute_id,
                label=slot_input.label.strip(),
                kind=slot_input.kind,
                start_time=slot_start,
                end_time=slot_end,
                position=slot_input.position,
                day_of_week=(
                    slot_input.dayOfWeek
                    if slot_input.kind in {"break", "activity"}
                    else None
                ),
                activity_id=slot_input.activityId,
            )
        )

    sections = {
        section.id: section
        for section in db.scalars(select(Section).where(Section.institute_id == institute_id))
    }
    member_roles = {
        member.user_id: member.role
        for member in db.scalars(
            select(InstituteMember).where(InstituteMember.institute_id == institute_id)
        )
    }
    subjects = {
        subject.id: subject
        for subject in db.scalars(select(Subject).where(Subject.institute_id == institute_id))
    }
    section_subjects = {
        (link.section_id, link.subject_id)
        for link in db.scalars(
            select(SectionSubject).where(
                SectionSubject.section_id.in_(sections.keys())
            )
        )
    }
    special_days = None
    if body.specialDays is not None:
        special_days = _build_special_days(
            db,
            institute_id,
            body.specialDays,
            sections,
            start,
            end,
        )

    entries = []
    entry_keys = set()
    entry_ids = set()
    for entry_input in body.entries:
        slot = next((slot for slot in slots if slot.id == entry_input.slotId), None)
        if not slot or slot.kind != "instruction":
            raise ValueError("Entries must use instruction slots")
        if entry_input.dayOfWeek not in body.settings.weekdays:
            raise ValueError("Entry day is not enabled for this schedule")
        if entry_input.sectionId not in sections:
            raise ValueError("Section does not belong to this institute")
        if entry_input.subjectId not in subjects:
            raise ValueError("Subject does not belong to this institute")
        if (entry_input.sectionId, entry_input.subjectId) not in section_subjects:
            raise ValueError("Subject is not assigned to this section")
        if entry_input.teacherId and member_roles.get(entry_input.teacherId) not in TEACHING_STAFF_ROLES:
            raise ValueError("Timetable teacher must be teaching staff in this institute")
        entry_key = (entry_input.dayOfWeek, entry_input.slotId, entry_input.sectionId)
        if entry_key in entry_keys:
            raise ValueError("A section can only have one entry in each period")
        entry_keys.add(entry_key)
        entry_id = entry_input.id or _new_id()
        if entry_id in entry_ids:
            raise ValueError("Timetable entry IDs must be unique")
        entry_ids.add(entry_id)
        entries.append(
            TimetableEntry(
                id=entry_id,
                institute_id=institute_id,
                slot_id=slot.id,
                day_of_week=entry_input.dayOfWeek,
                section_id=entry_input.sectionId,
                subject_id=entry_input.subjectId,
                teacher_id=entry_input.teacherId,
            )
        )

    _check_conflicts(entries, slots)
    db.execute(delete(TimetableEntry).where(TimetableEntry.institute_id == institute_id))
    if special_days is not None:
        _clear_special_days(db, institute_id)
    db.execute(delete(ScheduleSlot).where(ScheduleSlot.institute_id == institute_id))
    db.add_all(slots)
    db.add_all(entries)
    if special_days is not None:
        for special_day, activities in special_days:
            db.add(special_day)
            for activity, sections_for_activity, teachers_for_activity in activities:
                db.add(activity)
                db.add_all(
                    SpecialDayActivitySection(
                        special_activity_id=activity.id,
                        section_id=section_id,
                    )
                    for section_id in sections_for_activity
                )
                db.add_all(
                    SpecialDayActivityTeacher(
                        special_activity_id=activity.id,
                        teacher_id=teacher_id,
                    )
                    for teacher_id in teachers_for_activity
                )
    settings.timezone = body.settings.timezone
    settings.school_start = start
    settings.school_end = end
    settings.weekdays = ",".join(str(day) for day in body.settings.weekdays)
    settings.revision += 1
    db.commit()
    return get_schedule(db, institute_id)


def _build_special_days(
    db: Session,
    institute_id: str,
    inputs,
    sections: dict[str, Section],
    school_start: time,
    school_end: time,
) -> list[tuple[ScheduleSpecialDay, list[tuple[SpecialDayActivity, list[str], list[str]]]]]:
    member_roles = {
        member.user_id: member.role
        for member in db.scalars(
            select(InstituteMember).where(InstituteMember.institute_id == institute_id)
        )
    }
    days = []
    dates = set()
    for day_input in inputs:
        if day_input.date in dates:
            raise ValueError("Special days must use unique dates")
        dates.add(day_input.date)
        activities = []
        used_positions = set()
        for activity_input in day_input.activities:
            start = _parse_time(activity_input.start)
            end = _parse_time(activity_input.end)
            if start >= end or start < school_start or end > school_end:
                raise ValueError("Special activity must fit within school hours")
            if activity_input.position in used_positions:
                raise ValueError("Special activity positions must be unique")
            used_positions.add(activity_input.position)
            activity = db.get(Activity, activity_input.activityId)
            if not activity or activity.institute_id != institute_id:
                raise ValueError("Activity does not belong to this institute")
            if any(section_id not in sections for section_id in activity_input.sectionIds):
                raise ValueError("Special activity section does not belong to this institute")
            if any(
                member_roles.get(teacher_id) not in TEACHING_STAFF_ROLES
                for teacher_id in activity_input.teacherIds
            ):
                raise ValueError("Special activity teacher must be teaching staff")
            for existing, existing_sections, existing_teachers in activities:
                overlaps = start < existing.end_time and existing.start_time < end
                if overlaps and set(activity_input.sectionIds) & set(existing_sections):
                    raise ValueError("A section cannot have overlapping special activities")
                if overlaps and set(activity_input.teacherIds) & set(existing_teachers):
                    raise ValueError("A teacher cannot have overlapping special activities")
            activity_row = SpecialDayActivity(
                id=_new_id(),
                special_day_id="",
                activity_id=activity_input.activityId,
                start_time=start,
                end_time=end,
                position=activity_input.position,
            )
            activities.append(
                (activity_row, activity_input.sectionIds, activity_input.teacherIds)
            )
        special_day = ScheduleSpecialDay(
            id=_new_id(),
            institute_id=institute_id,
            special_date=day_input.date,
            label=day_input.label.strip(),
            replace_regular=day_input.replaceRegular,
        )
        for activity, _, _ in activities:
            activity.special_day_id = special_day.id
        days.append((special_day, activities))
    return days


def _clear_special_days(db: Session, institute_id: str) -> None:
    day_ids = select(ScheduleSpecialDay.id).where(
        ScheduleSpecialDay.institute_id == institute_id
    )
    activity_ids = select(SpecialDayActivity.id).where(
        SpecialDayActivity.special_day_id.in_(day_ids)
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
    db.execute(delete(SpecialDayActivity).where(SpecialDayActivity.id.in_(activity_ids)))
    db.execute(delete(ScheduleSpecialDay).where(ScheduleSpecialDay.institute_id == institute_id))


def _check_conflicts(entries: list[TimetableEntry], slots: list[ScheduleSlot]) -> None:
    slot_by_id = {slot.id: slot for slot in slots}
    for index, entry in enumerate(entries):
        current = slot_by_id[entry.slot_id]
        for other in entries[index + 1 :]:
            if other.day_of_week != entry.day_of_week:
                continue
            other_slot = slot_by_id[other.slot_id]
            same_section = other.section_id == entry.section_id
            if same_section and (
                current.start_time < other_slot.end_time
                and other_slot.start_time < current.end_time
            ):
                raise ValueError("A section cannot have overlapping periods")
            same_teacher = entry.teacher_id and entry.teacher_id == other.teacher_id
            if same_teacher and (
                current.start_time < other_slot.end_time
                and other_slot.start_time < current.end_time
            ):
                raise ValueError("A teacher cannot have overlapping periods")


def _output(
    settings: ScheduleSettings,
    slots: list[ScheduleSlot],
    entries: list[TimetableEntry],
    special_days: list[ScheduleSpecialDay],
    visible_sections: set[str] | None,
    db: Session,
) -> dict:
    serialized_days = []
    for day in special_days:
        serialized_activities = []
        activities = db.scalars(
            select(SpecialDayActivity)
            .where(SpecialDayActivity.special_day_id == day.id)
            .order_by(SpecialDayActivity.position)
        )
        for activity in activities:
            section_ids = list(
                db.scalars(
                    select(SpecialDayActivitySection.section_id).where(
                        SpecialDayActivitySection.special_activity_id == activity.id
                    )
                )
            )
            if visible_sections is not None and not visible_sections.intersection(section_ids):
                continue
            if visible_sections is not None:
                section_ids = [section_id for section_id in section_ids if section_id in visible_sections]
            teacher_ids = list(
                db.scalars(
                    select(SpecialDayActivityTeacher.teacher_id).where(
                        SpecialDayActivityTeacher.special_activity_id == activity.id
                    )
                )
            )
            serialized_activities.append(
                {
                    "id": activity.id,
                    "activityId": activity.activity_id,
                    "start": activity.start_time.strftime("%H:%M"),
                    "end": activity.end_time.strftime("%H:%M"),
                    "position": activity.position,
                    "sectionIds": section_ids,
                    "teacherIds": teacher_ids,
                }
            )
        if visible_sections is None or serialized_activities:
            serialized_days.append(
                {
                    "id": day.id,
                    "date": day.special_date,
                    "label": day.label,
                    "replaceRegular": day.replace_regular,
                    "activities": serialized_activities,
                }
            )
    return {
        "instituteId": settings.institute_id,
        "revision": settings.revision,
        "settings": {
            "timezone": settings.timezone,
            "schoolStart": settings.school_start.strftime("%H:%M"),
            "schoolEnd": settings.school_end.strftime("%H:%M"),
            "weekdays": [int(day) for day in settings.weekdays.split(",") if day],
        },
        "slots": [
            {
                "id": slot.id,
                "label": slot.label,
                "kind": slot.kind,
                "start": slot.start_time.strftime("%H:%M"),
                "end": slot.end_time.strftime("%H:%M"),
                "position": slot.position,
                "dayOfWeek": slot.day_of_week,
                "activityId": slot.activity_id,
            }
            for slot in slots
        ],
        "entries": [
            {
                "id": entry.id,
                "dayOfWeek": entry.day_of_week,
                "slotId": entry.slot_id,
                "sectionId": entry.section_id,
                "subjectId": entry.subject_id,
                "teacherId": entry.teacher_id,
            }
            for entry in entries
        ],
        "specialDays": serialized_days,
    }


def _parse_time(value: str) -> time:
    if len(value) != 5 or value[2] != ":":
        raise ValueError(f"Invalid time: {value}")
    try:
        return time.fromisoformat(value)
    except ValueError as error:
        raise ValueError(f"Invalid time: {value}") from error


def _new_id() -> str:
    import uuid

    return str(uuid.uuid4())
