import json
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import DailyNote
from app.services.sections import (
    assert_subject_in_section,
    can_edit_daily_note,
    require_daily_note_editor,
    require_section_access,
)


def _parse_attachments(raw: str) -> list[dict]:
    if not raw:
        return []
    try:
        data = json.loads(raw)
        return data if isinstance(data, list) else []
    except json.JSONDecodeError:
        return []


def note_to_dict(note: DailyNote, *, editable: bool) -> dict:
    return {
        "id": note.id,
        "subjectId": note.subject_id,
        "content": note.content,
        "noteDate": note.note_date,
        "teacherId": note.teacher_id,
        "drawingJson": note.drawing_json or "",
        "attachments": _parse_attachments(note.attachments_json or "[]"),
        "editable": editable,
    }


def list_notes(
    db: Session, section_id: str, user_id: str, subject_id: str | None = None
) -> list[dict]:
    section = require_section_access(db, section_id, user_id)
    today = date.today()
    query = select(DailyNote).where(DailyNote.section_id == section_id)
    if subject_id:
        assert_subject_in_section(db, section_id, subject_id)
        query = query.where(DailyNote.subject_id == subject_id)
    rows = db.scalars(query.order_by(DailyNote.note_date.desc(), DailyNote.subject_id))
    return [
        note_to_dict(
            row,
            editable=row.note_date == today
            and can_edit_daily_note(db, section, row.subject_id, user_id, row.note_date),
        )
        for row in rows
    ]


def get_note_for_date(
    db: Session, section_id: str, subject_id: str, user_id: str, note_date: date
) -> dict:
    section = require_section_access(db, section_id, user_id)
    assert_subject_in_section(db, section_id, subject_id)
    today = date.today()
    editable = note_date == today and can_edit_daily_note(
        db, section, subject_id, user_id, note_date
    )
    note = db.scalar(
        select(DailyNote).where(
            DailyNote.section_id == section_id,
            DailyNote.subject_id == subject_id,
            DailyNote.note_date == note_date,
        )
    )
    if not note:
        return {
            "id": None,
            "subjectId": subject_id,
            "content": "",
            "noteDate": note_date,
            "teacherId": None,
            "drawingJson": "",
            "attachments": [],
            "editable": editable,
        }
    return note_to_dict(note, editable=editable)


def _validate_attachments(attachments: list) -> str:
    if len(attachments) > 8:
        raise ValueError("At most 8 photos per daily note")
    cleaned = []
    for item in attachments:
        name = str(item.get("name", "photo"))[:120]
        content_type = str(item.get("contentType", "image/jpeg"))[:64]
        data_url = str(item.get("dataUrl", ""))
        if not data_url.startswith("data:image/"):
            raise ValueError("Attachments must be image uploads")
        if len(data_url) > 2_500_000:
            raise ValueError("Each photo must be under 2 MB")
        cleaned.append(
            {"id": str(item.get("id", "")), "name": name, "contentType": content_type, "dataUrl": data_url}
        )
    return json.dumps(cleaned)


def upsert_note_for_date(
    db: Session,
    section_id: str,
    subject_id: str,
    user_id: str,
    note_date: date,
    content: str,
    drawing_json: str,
    attachments: list,
) -> dict:
    require_daily_note_editor(db, section_id, subject_id, user_id)
    today = date.today()
    if note_date != today:
        raise PermissionError("Only today's daily note can be edited")

    if len(drawing_json) > 800_000:
        raise ValueError("Drawing is too large to save")

    note = db.scalar(
        select(DailyNote).where(
            DailyNote.section_id == section_id,
            DailyNote.subject_id == subject_id,
            DailyNote.note_date == note_date,
        )
    )
    attachments_json = _validate_attachments(attachments)
    if not note:
        note = DailyNote(
            section_id=section_id,
            subject_id=subject_id,
            teacher_id=user_id,
            content=content,
            note_date=note_date,
            drawing_json=drawing_json,
            attachments_json=attachments_json,
        )
        db.add(note)
    else:
        note.content = content
        note.drawing_json = drawing_json
        note.attachments_json = attachments_json
        note.teacher_id = user_id
    db.commit()
    db.refresh(note)
    return note_to_dict(note, editable=True)
