import uuid
from datetime import date, datetime, timezone

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models import (
    InstituteMember,
    PublishedTimetableEntry,
    ScheduleSettings,
    ScheduleSlot,
    Section,
    SectionSubject,
    Subject,
    TeacherAbsence,
    TeacherSubjectAssignment,
    TimetableEntry,
    TimetableSubstitution,
)
from app.roles import TEACHING_STAFF_ROLES


def _instruction_slots(db: Session, institute_id: str) -> list[ScheduleSlot]:
    return list(
        db.scalars(
            select(ScheduleSlot)
            .where(
                ScheduleSlot.institute_id == institute_id,
                ScheduleSlot.kind == "instruction",
            )
            .order_by(ScheduleSlot.position)
        )
    )


def _slot_period_map(slots: list[ScheduleSlot]) -> dict[str, int]:
    return {slot.id: index + 1 for index, slot in enumerate(slots)}


def _entries_overlap(slot_a: ScheduleSlot, slot_b: ScheduleSlot) -> bool:
    return slot_a.start_time < slot_b.end_time and slot_b.start_time < slot_a.end_time


def _entry_snapshot(entry) -> tuple:
    return (
        entry.slot_id,
        entry.day_of_week,
        entry.section_id,
        entry.subject_id,
        entry.teacher_id,
        entry.room or "",
        entry.locked,
    )


def entries_changed_since_publish(db: Session, institute_id: str) -> bool:
    settings = db.get(ScheduleSettings, institute_id)
    if not settings or not settings.published_at:
        return False
    published = {
        _entry_snapshot(row)
        for row in db.scalars(
            select(PublishedTimetableEntry).where(
                PublishedTimetableEntry.institute_id == institute_id
            )
        )
    }
    draft = {
        _entry_snapshot(row)
        for row in db.scalars(
            select(TimetableEntry).where(TimetableEntry.institute_id == institute_id)
        )
    }
    return published != draft


def detect_clashes(db: Session, institute_id: str) -> list[dict]:
    slots = _instruction_slots(db, institute_id)
    slot_by_id = {slot.id: slot for slot in slots}
    period_by_slot = _slot_period_map(slots)
    entries = list(
        db.scalars(select(TimetableEntry).where(TimetableEntry.institute_id == institute_id))
    )
    clashes: list[dict] = []
    clash_index = 0

    for index, entry in enumerate(entries):
        slot = slot_by_id.get(entry.slot_id)
        if not slot:
            continue
        for other in entries[index + 1 :]:
            other_slot = slot_by_id.get(other.slot_id)
            if not other.day_of_week == entry.day_of_week or not other_slot:
                continue
            if not _entries_overlap(slot, other_slot):
                continue
            period_no = period_by_slot.get(entry.slot_id, 0)
            if entry.teacher_id and entry.teacher_id == other.teacher_id:
                clash_index += 1
                clashes.append(
                    {
                        "clashId": f"teacher-{clash_index}",
                        "type": "teacher",
                        "day": entry.day_of_week,
                        "periodNo": period_no,
                        "sectionIds": sorted({entry.section_id, other.section_id}),
                        "teacherId": entry.teacher_id,
                        "message": "Teacher is scheduled in two sections in the same period",
                    }
                )
            if entry.room and entry.room == other.room:
                clash_index += 1
                clashes.append(
                    {
                        "clashId": f"room-{clash_index}",
                        "type": "room",
                        "day": entry.day_of_week,
                        "periodNo": period_no,
                        "sectionIds": sorted({entry.section_id, other.section_id}),
                        "room": entry.room,
                        "message": f"Room {entry.room} is double booked",
                    }
                )

    section_subject_limits = {
        (link.section_id, link.subject_id): link.weekly_periods
        for link in db.scalars(
            select(SectionSubject).join(Section).where(Section.institute_id == institute_id)
        )
        if link.weekly_periods is not None
    }
    usage: dict[tuple[str, str], int] = {}
    for entry in entries:
        usage[(entry.section_id, entry.subject_id)] = (
            usage.get((entry.section_id, entry.subject_id), 0) + 1
        )
    for (section_id, subject_id), count in usage.items():
        limit = section_subject_limits.get((section_id, subject_id))
        if limit is not None and count > limit:
            clash_index += 1
            subject_name = db.scalar(select(Subject.name).where(Subject.id == subject_id)) or ""
            clashes.append(
                {
                    "clashId": f"subject_count-{clash_index}",
                    "type": "subject_count",
                    "day": 0,
                    "periodNo": 0,
                    "sectionIds": [section_id],
                    "message": f"{subject_name} has {count} periods but only {limit} are allowed",
                }
            )
    return clashes


def list_clashes(db: Session, institute_id: str) -> dict:
    return {"items": detect_clashes(db, institute_id)}


def _load_entries(
    db: Session, institute_id: str, state: str
) -> list[TimetableEntry | PublishedTimetableEntry]:
    if state == "published":
        return list(
            db.scalars(
                select(PublishedTimetableEntry).where(
                    PublishedTimetableEntry.institute_id == institute_id
                )
            )
        )
    return list(
        db.scalars(select(TimetableEntry).where(TimetableEntry.institute_id == institute_id))
    )


def _cell_status(entry, clashes: list[dict], section_id: str, slot_id: str, day: int) -> tuple[str, str | None]:
    for clash in clashes:
        if clash["day"] == day and section_id in clash.get("sectionIds", []):
            if clash["type"] in {"teacher", "room"}:
                entry_slots = {slot_id}
                if clash.get("teacherId") == entry.teacher_id or clash.get("room") == entry.room:
                    return "clash", clash["message"]
            if clash["type"] == "subject_count" and entry.section_id == section_id:
                return "clash", clash["message"]
    if entry.locked:
        return "locked", None
    return "ok", None


def get_timetable(
    db: Session,
    institute_id: str,
    *,
    view: str = "class",
    item_id: str | None = None,
    state: str = "draft",
) -> dict:
    settings = db.get(ScheduleSettings, institute_id)
    if not settings:
        settings = ScheduleSettings(institute_id=institute_id)
        db.add(settings)
        db.commit()
        db.refresh(settings)

    slots = _instruction_slots(db, institute_id)
    period_by_slot = _slot_period_map(slots)
    weekdays = [int(day) for day in settings.weekdays.split(",") if day]
    entries = _load_entries(db, institute_id, state)
    clashes = detect_clashes(db, institute_id) if state == "draft" else []

    if view == "class" and item_id:
        entries = [entry for entry in entries if entry.section_id == item_id]
    elif view == "teacher" and item_id:
        entries = [entry for entry in entries if entry.teacher_id == item_id]
    elif view == "room" and item_id:
        entries = [entry for entry in entries if entry.room == item_id]

    subject_names = {
        subject.id: subject.name
        for subject in db.scalars(select(Subject).where(Subject.institute_id == institute_id))
    }

    cells = []
    for entry in entries:
        period_no = period_by_slot.get(entry.slot_id, 0)
        status, clash_reason = _cell_status(entry, clashes, entry.section_id, entry.slot_id, entry.day_of_week)
        cells.append(
            {
                "day": entry.day_of_week,
                "periodNo": period_no,
                "slotId": entry.slot_id,
                "sectionId": entry.section_id,
                "subjectId": entry.subject_id,
                "subjectName": subject_names.get(entry.subject_id, ""),
                "teacherId": entry.teacher_id,
                "teacherName": "",
                "room": entry.room,
                "locked": entry.locked,
                "status": status,
                "clashReason": clash_reason,
            }
        )

    return {
        "view": view,
        "itemId": item_id,
        "state": state,
        "periods": [
            {
                "periodNo": period_by_slot[slot.id],
                "slotId": slot.id,
                "start": slot.start_time.strftime("%H:%M"),
                "end": slot.end_time.strftime("%H:%M"),
                "kind": "class",
            }
            for slot in slots
        ],
        "days": [
            {
                "day": day,
                "isWorking": day in weekdays,
                "halfDay": False,
            }
            for day in range(1, 8)
        ],
        "cells": cells,
        "draftSavedAt": settings.draft_saved_at,
        "publishedAt": settings.published_at,
        "changedSincePublish": entries_changed_since_publish(db, institute_id),
    }


def patch_cell(db: Session, institute_id: str, body) -> dict:
    settings = db.get(ScheduleSettings, institute_id)
    if not settings:
        settings = ScheduleSettings(institute_id=institute_id)
        db.add(settings)
        db.flush()

    entry = db.scalar(
        select(TimetableEntry).where(
            TimetableEntry.institute_id == institute_id,
            TimetableEntry.section_id == body.sectionId,
            TimetableEntry.day_of_week == body.dayOfWeek,
            TimetableEntry.slot_id == body.slotId,
        )
    )

    if body.clear:
        if entry and entry.locked:
            raise ValueError("This cell is locked")
        if entry:
            db.delete(entry)
        settings.draft_saved_at = datetime.now(timezone.utc)
        db.commit()
        return get_timetable(
            db, institute_id, view="class", item_id=body.sectionId, state="draft"
        )

    if not body.subjectId:
        raise ValueError("Subject is required")

    member_roles = {
        member.user_id: member.role
        for member in db.scalars(
            select(InstituteMember).where(InstituteMember.institute_id == institute_id)
        )
    }

    if body.teacherId and member_roles.get(body.teacherId) not in TEACHING_STAFF_ROLES:
        raise ValueError("Timetable teacher must be teaching staff in this institute")

    if entry and entry.locked and body.locked is not True:
        if body.subjectId != entry.subject_id or body.teacherId != entry.teacher_id:
            raise ValueError("This cell is locked")

    if not entry:
        entry = TimetableEntry(
            id=str(uuid.uuid4()),
            institute_id=institute_id,
            slot_id=body.slotId,
            day_of_week=body.dayOfWeek,
            section_id=body.sectionId,
            subject_id=body.subjectId,
            teacher_id=body.teacherId,
        )
        db.add(entry)
    else:
        entry.subject_id = body.subjectId
        entry.teacher_id = body.teacherId

    if body.room is not None:
        entry.room = body.room.strip()[:30] or None
    if body.locked is not None:
        entry.locked = body.locked

    settings.draft_saved_at = datetime.now(timezone.utc)
    db.commit()
    return get_timetable(db, institute_id, view="class", item_id=body.sectionId, state="draft")


def teacher_load(db: Session, institute_id: str, *, view: str, item_id: str) -> dict:
    if view != "class" or not item_id:
        raise ValueError("Teacher load requires view=class and an item id")

    entries = list(
        db.scalars(
            select(TimetableEntry).where(
                TimetableEntry.institute_id == institute_id,
                TimetableEntry.section_id == item_id,
            )
        )
    )
    limits = {
        link.subject_id: link.weekly_periods
        for link in db.scalars(
            select(SectionSubject).where(SectionSubject.section_id == item_id)
        )
    }
    subject_names = {
        subject.id: subject.name
        for subject in db.scalars(
            select(Subject).join(SectionSubject).where(SectionSubject.section_id == item_id)
        )
    }

    by_teacher_subject: dict[tuple[str, str], int] = {}
    for entry in entries:
        if not entry.teacher_id:
            continue
        key = (entry.teacher_id, entry.subject_id)
        by_teacher_subject[key] = by_teacher_subject.get(key, 0) + 1

    items = []
    for (teacher_id, subject_id), periods_used in sorted(by_teacher_subject.items()):
        items.append(
            {
                "teacherId": teacher_id,
                "name": "",
                "subject": subject_names.get(subject_id, ""),
                "periodsUsed": periods_used,
                "periodsNeeded": limits.get(subject_id),
            }
        )
    return {"items": items}


def _teacher_busy(
    entries: list[TimetableEntry],
    slots: list[ScheduleSlot],
    *,
    teacher_id: str,
    day: int,
    slot_id: str,
    section_id: str,
) -> bool:
    slot_by_id = {slot.id: slot for slot in slots}
    current = slot_by_id.get(slot_id)
    if not current:
        return True
    for entry in entries:
        if entry.section_id == section_id and entry.day_of_week == day and entry.slot_id == slot_id:
            continue
        if entry.teacher_id != teacher_id or entry.day_of_week != day:
            continue
        other = slot_by_id.get(entry.slot_id)
        if not other:
            continue
        if current.start_time < other.end_time and other.start_time < current.end_time:
            return True
    return False


def _sections_for_scope(
    db: Session, institute_id: str, section_ids: list[str] | None, campus_id: str | None
) -> list[Section]:
    sections = list(
        db.scalars(select(Section).where(Section.institute_id == institute_id).order_by(Section.class_name, Section.name))
    )
    if section_ids:
        allowed = set(section_ids)
        sections = [section for section in sections if section.id in allowed]
    if campus_id:
        sections = [
            section
            for section in sections
            if section.branch_id == campus_id or section.branch_id is None
        ]
    return sections


def preview_auto_fill(
    db: Session,
    institute_id: str,
    *,
    section_ids: list[str] | None = None,
    campus_id: str | None = None,
) -> dict:
    settings = db.get(ScheduleSettings, institute_id)
    weekdays = [int(day) for day in (settings.weekdays.split(",") if settings else "1,2,3,4,5") if day]
    slots = _instruction_slots(db, institute_id)
    period_by_slot = _slot_period_map(slots)
    entries = list(
        db.scalars(select(TimetableEntry).where(TimetableEntry.institute_id == institute_id))
    )
    existing = {
        (entry.section_id, entry.day_of_week, entry.slot_id): entry for entry in entries
    }
    usage: dict[tuple[str, str], int] = {}
    for entry in entries:
        usage[(entry.section_id, entry.subject_id)] = (
            usage.get((entry.section_id, entry.subject_id), 0) + 1
        )
    limits = {
        (link.section_id, link.subject_id): link.weekly_periods
        for link in db.scalars(
            select(SectionSubject).join(Section).where(Section.institute_id == institute_id)
        )
        if link.weekly_periods is not None
    }
    subject_names = {
        subject.id: subject.name
        for subject in db.scalars(select(Subject).where(Subject.institute_id == institute_id))
    }
    proposed: list[dict] = []
    could_not_fill: list[dict] = []
    sections = _sections_for_scope(db, institute_id, section_ids, campus_id)

    for section in sections:
        links = list(
            db.scalars(select(SectionSubject).where(SectionSubject.section_id == section.id))
        )
        for day in weekdays:
            for slot in slots:
                key = (section.id, day, slot.id)
                entry = existing.get(key)
                if entry and entry.locked:
                    continue
                if entry and entry.subject_id:
                    continue
                deficit_subjects = []
                for link in links:
                    limit = limits.get((section.id, link.subject_id))
                    if limit is None:
                        continue
                    used = usage.get((section.id, link.subject_id), 0)
                    if used < limit:
                        deficit_subjects.append((limit - used, link.subject_id))
                if not deficit_subjects:
                    could_not_fill.append(
                        {
                            "sectionId": section.id,
                            "day": day,
                            "periodNo": period_by_slot.get(slot.id, 0),
                            "slotId": slot.id,
                            "reason": "All subjects already have enough periods",
                        }
                    )
                    continue
                deficit_subjects.sort(key=lambda item: (-item[0], subject_names.get(item[1], "")))
                subject_id = deficit_subjects[0][1]
                teacher_id = db.scalar(
                    select(TeacherSubjectAssignment.teacher_id).where(
                        TeacherSubjectAssignment.section_id == section.id,
                        TeacherSubjectAssignment.subject_id == subject_id,
                    )
                )
                if not teacher_id:
                    could_not_fill.append(
                        {
                            "sectionId": section.id,
                            "day": day,
                            "periodNo": period_by_slot.get(slot.id, 0),
                            "slotId": slot.id,
                            "reason": "No teacher assigned for this subject",
                        }
                    )
                    continue
                if _teacher_busy(
                    entries,
                    slots,
                    teacher_id=teacher_id,
                    day=day,
                    slot_id=slot.id,
                    section_id=section.id,
                ):
                    could_not_fill.append(
                        {
                            "sectionId": section.id,
                            "day": day,
                            "periodNo": period_by_slot.get(slot.id, 0),
                            "slotId": slot.id,
                            "reason": f"Teacher {teacher_id} is busy in this period",
                        }
                    )
                    continue
                proposal = {
                    "sectionId": section.id,
                    "dayOfWeek": day,
                    "slotId": slot.id,
                    "periodNo": period_by_slot.get(slot.id, 0),
                    "subjectId": subject_id,
                    "subjectName": subject_names.get(subject_id, ""),
                    "teacherId": teacher_id,
                    "selected": True,
                }
                proposed.append(proposal)
                usage[(section.id, subject_id)] = usage.get((section.id, subject_id), 0) + 1
                entries.append(
                    TimetableEntry(
                        institute_id=institute_id,
                        slot_id=slot.id,
                        day_of_week=day,
                        section_id=section.id,
                        subject_id=subject_id,
                        teacher_id=teacher_id,
                    )
                )

    needs_decision = sum(1 for item in could_not_fill if item["reason"].startswith("Teacher"))
    return {
        "proposedCount": len(proposed),
        "needsDecisionCount": needs_decision,
        "proposed": proposed,
        "couldNotFill": could_not_fill,
    }


def accept_auto_fill(db: Session, institute_id: str, proposals: list) -> dict:
    settings = db.get(ScheduleSettings, institute_id)
    if not settings:
        settings = ScheduleSettings(institute_id=institute_id)
        db.add(settings)
        db.flush()
    applied = 0
    for item in proposals:
        if not item.get("selected", True):
            continue
        entry = db.scalar(
            select(TimetableEntry).where(
                TimetableEntry.institute_id == institute_id,
                TimetableEntry.section_id == item["sectionId"],
                TimetableEntry.day_of_week == item["dayOfWeek"],
                TimetableEntry.slot_id == item["slotId"],
            )
        )
        if entry and entry.locked:
            continue
        if entry and entry.subject_id:
            continue
        if not entry:
            entry = TimetableEntry(
                id=str(uuid.uuid4()),
                institute_id=institute_id,
                slot_id=item["slotId"],
                day_of_week=item["dayOfWeek"],
                section_id=item["sectionId"],
                subject_id=item["subjectId"],
                teacher_id=item.get("teacherId"),
            )
            db.add(entry)
        else:
            entry.subject_id = item["subjectId"]
            entry.teacher_id = item.get("teacherId")
        applied += 1
    settings.draft_saved_at = datetime.now(timezone.utc)
    db.commit()
    return {"appliedCount": applied}


def _day_of_week_for_date(target: date) -> int:
    return target.isoweekday()


def list_substitutions(db: Session, institute_id: str, target: date) -> dict:
    day = _day_of_week_for_date(target)
    slots = _instruction_slots(db, institute_id)
    period_by_slot = _slot_period_map(slots)
    absences = list(
        db.scalars(
            select(TeacherAbsence).where(
                TeacherAbsence.institute_id == institute_id,
                TeacherAbsence.absence_date == target,
            )
        )
    )
    absent_ids = {row.teacher_id for row in absences}
    if not absent_ids:
        return {"date": target, "items": []}
    entries = list(
        db.scalars(
            select(TimetableEntry).where(
                TimetableEntry.institute_id == institute_id,
                TimetableEntry.day_of_week == day,
                TimetableEntry.teacher_id.in_(absent_ids),
            )
        )
    )
    saved = {
        (row.slot_id, row.section_id): row
        for row in db.scalars(
            select(TimetableSubstitution).where(
                TimetableSubstitution.institute_id == institute_id,
                TimetableSubstitution.substitution_date == target,
            )
        )
    }
    grouped: dict[str, dict] = {}
    for entry in entries:
        absence = next((a for a in absences if a.teacher_id == entry.teacher_id), None)
        if not absence:
            continue
        bucket = grouped.setdefault(
            entry.teacher_id,
            {
                "teacherId": entry.teacher_id,
                "note": absence.note,
                "periods": [],
            },
        )
        sub = saved.get((entry.slot_id, entry.section_id))
        bucket["periods"].append(
            {
                "sectionId": entry.section_id,
                "slotId": entry.slot_id,
                "periodNo": period_by_slot.get(entry.slot_id, 0),
                "substituteTeacherId": sub.substitute_teacher_id if sub else None,
                "substitutionId": sub.id if sub else None,
            }
        )
    return {"date": target, "items": list(grouped.values())}


def save_substitutions(db: Session, institute_id: str, target: date, rows: list) -> dict:
    day = _day_of_week_for_date(target)
    slots = _instruction_slots(db, institute_id)
    entries = list(
        db.scalars(select(TimetableEntry).where(TimetableEntry.institute_id == institute_id))
    )
    member_roles = {
        member.user_id: member.role
        for member in db.scalars(
            select(InstituteMember).where(InstituteMember.institute_id == institute_id)
        )
    }
    absent_today = {
        row.teacher_id
        for row in db.scalars(
            select(TeacherAbsence).where(
                TeacherAbsence.institute_id == institute_id,
                TeacherAbsence.absence_date == target,
            )
        )
    }
    saved_count = 0
    for row in rows:
        substitute_id = row["substituteTeacherId"]
        if member_roles.get(substitute_id) not in TEACHING_STAFF_ROLES:
            raise ValueError("Substitute must be teaching staff")
        if substitute_id in absent_today:
            raise ValueError("Substitute cannot be absent on this date")
        if _teacher_busy(
            entries,
            slots,
            teacher_id=substitute_id,
            day=day,
            slot_id=row["slotId"],
            section_id=row["sectionId"],
        ):
            raise ValueError("Substitute is busy in this period")
        original_id = row.get("originalTeacherId")
        if not original_id:
            entry = db.scalar(
                select(TimetableEntry).where(
                    TimetableEntry.institute_id == institute_id,
                    TimetableEntry.section_id == row["sectionId"],
                    TimetableEntry.day_of_week == day,
                    TimetableEntry.slot_id == row["slotId"],
                )
            )
            original_id = entry.teacher_id if entry else None
        if not original_id:
            raise ValueError("Original teacher not found for this period")
        existing = db.scalar(
            select(TimetableSubstitution).where(
                TimetableSubstitution.institute_id == institute_id,
                TimetableSubstitution.substitution_date == target,
                TimetableSubstitution.slot_id == row["slotId"],
                TimetableSubstitution.section_id == row["sectionId"],
            )
        )
        if existing:
            existing.substitute_teacher_id = substitute_id
            existing.original_teacher_id = original_id
        else:
            db.add(
                TimetableSubstitution(
                    institute_id=institute_id,
                    substitution_date=target,
                    slot_id=row["slotId"],
                    section_id=row["sectionId"],
                    original_teacher_id=original_id,
                    substitute_teacher_id=substitute_id,
                )
            )
        saved_count += 1
    db.commit()
    return list_substitutions(db, institute_id, target) | {"savedCount": saved_count}


def publish_timetable(db: Session, institute_id: str) -> dict:
    clashes = detect_clashes(db, institute_id)
    if clashes:
        raise ValueError("Fix clashes before publishing")

    settings = db.get(ScheduleSettings, institute_id)
    if not settings:
        settings = ScheduleSettings(institute_id=institute_id)
        db.add(settings)
        db.flush()

    draft_entries = list(
        db.scalars(select(TimetableEntry).where(TimetableEntry.institute_id == institute_id))
    )
    db.execute(
        delete(PublishedTimetableEntry).where(PublishedTimetableEntry.institute_id == institute_id)
    )
    for entry in draft_entries:
        db.add(
            PublishedTimetableEntry(
                id=entry.id,
                institute_id=entry.institute_id,
                slot_id=entry.slot_id,
                day_of_week=entry.day_of_week,
                section_id=entry.section_id,
                subject_id=entry.subject_id,
                teacher_id=entry.teacher_id,
                room=entry.room,
                locked=entry.locked,
            )
        )
    settings.published_at = datetime.now(timezone.utc)
    db.commit()
    return {
        "publishedAt": settings.published_at,
        "cellCount": len(draft_entries),
        "changedSincePublish": False,
    }
