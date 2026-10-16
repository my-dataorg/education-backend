from sqlalchemy.orm import Session

from app.services.institutes import _role_settings, require_manage


def get_role_settings(db: Session, institute_id: str) -> dict:
    settings = _role_settings(db, institute_id)
    return {"principalCanEditTimetable": settings.principal_can_edit_timetable}


def update_role_settings(db: Session, institute_id: str, user_id: str, body) -> dict:
    require_manage(db, institute_id, user_id)
    settings = _role_settings(db, institute_id)
    if body.principalCanEditTimetable is not None:
        settings.principal_can_edit_timetable = body.principalCanEditTimetable
    db.commit()
    db.refresh(settings)
    return get_role_settings(db, institute_id)
