from datetime import time

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import (
    Activity,
    ScheduleSettings,
    ScheduleSlot,
    Section,
    SectionMember,
    Subject,
    TimetableEntry,
)
from app.services.institutes import get_membership


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
        if member and member.role not in {"owner", "admin"}:
            section_ids = select(SectionMember.section_id).where(SectionMember.user_id == user_id)
            entries_query = entries_query.where(TimetableEntry.section_id.in_(section_ids))
    entries = list(db.scalars(entries_query))
    return _output(settings, slots, entries)


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
    subjects = {
        subject.id: subject
        for subject in db.scalars(select(Subject).where(Subject.institute_id == institute_id))
    }

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
    db.execute(delete(ScheduleSlot).where(ScheduleSlot.institute_id == institute_id))
    db.add_all(slots)
    db.add_all(entries)
    settings.timezone = body.settings.timezone
    settings.school_start = start
    settings.school_end = end
    settings.weekdays = ",".join(str(day) for day in body.settings.weekdays)
    settings.revision += 1
    db.commit()
    return get_schedule(db, institute_id)


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


def _output(settings: ScheduleSettings, slots: list[ScheduleSlot], entries: list[TimetableEntry]) -> dict:
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
