import json
from datetime import date, datetime, timezone

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


def _can_view_note_body(
    db: Session, section, subject_id: str, user_id: str, note: DailyNote | None, note_date: date
) -> bool:
    if not note:
        return False
    if note.published_at is not None:
        return True
    return can_edit_daily_note(db, section, subject_id, user_id, note_date)


def _empty_shell(
    subject_id: str,
    note_date: date,
    *,
    editable: bool,
    institute_today: date,
    published_at: datetime | None = None,
) -> dict:
    return {
        "id": None,
        "subjectId": subject_id,
        "content": "",
        "noteDate": note_date,
        "teacherId": None,
        "drawingJson": "",
        "attachments": [],
        "editable": editable,
        "publishedAt": published_at.isoformat() if published_at else None,
        "instituteToday": institute_today.isoformat(),
    }


def note_to_dict(
    note: DailyNote,
    *,
    editable: bool,
    institute_today: date,
    viewer_can_see_body: bool,
) -> dict:
    if not viewer_can_see_body:
        return _empty_shell(
            note.subject_id,
            note.note_date,
            editable=editable,
            institute_today=institute_today,
            published_at=None,
        )
    return {
        "id": note.id,
        "subjectId": note.subject_id,
        "content": note.content,
        "noteDate": note.note_date,
        "teacherId": note.teacher_id,
        "drawingJson": note.drawing_json or "",
        "attachments": _parse_attachments(note.attachments_json or "[]"),
        "editable": editable,
        "publishedAt": note.published_at.isoformat() if note.published_at else None,
        "instituteToday": institute_today.isoformat(),
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
    out: list[dict] = []
    for row in rows:
        editable = row.note_date == today and can_edit_daily_note(
            db, section, row.subject_id, user_id, row.note_date
        )
        if not _can_view_note_body(db, section, row.subject_id, user_id, row, row.note_date):
            continue
        out.append(
            note_to_dict(
                row,
                editable=editable,
                institute_today=today,
                viewer_can_see_body=True,
            )
        )
    return out


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
        return _empty_shell(subject_id, note_date, editable=editable, institute_today=today)
    can_see = _can_view_note_body(db, section, subject_id, user_id, note, note_date)
    return note_to_dict(
        note, editable=editable, institute_today=today, viewer_can_see_body=can_see
    )


def _validate_attachments(attachments: list) -> str:
    if len(attachments) > 8:
        raise ValueError("At most 8 photos per class board")
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
        raise PermissionError("Only today's class board can be edited")

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
            published_at=None,
        )
        db.add(note)
    else:
        note.content = content
        note.drawing_json = drawing_json
        note.attachments_json = attachments_json
        note.teacher_id = user_id
    db.commit()
    db.refresh(note)
    return note_to_dict(
        note, editable=True, institute_today=today, viewer_can_see_body=True
    )


def publish_note_for_date(
    db: Session,
    section_id: str,
    subject_id: str,
    user_id: str,
    note_date: date,
    content: str,
    drawing_json: str,
    attachments: list,
) -> dict:
    """Save latest draft and mark visible to students, parents, and other staff."""
    upsert_note_for_date(
        db,
        section_id,
        subject_id,
        user_id,
        note_date,
        content,
        drawing_json,
        attachments,
    )
    note = db.scalar(
        select(DailyNote).where(
            DailyNote.section_id == section_id,
            DailyNote.subject_id == subject_id,
            DailyNote.note_date == note_date,
        )
    )
    if not note:
        raise ValueError("Class board not found")
    note.published_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(note)
    return note_to_dict(
        note, editable=True, institute_today=date.today(), viewer_can_see_body=True
    )
