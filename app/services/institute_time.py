from datetime import date, datetime
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from app.models import ScheduleSettings

DEFAULT_TZ = "Asia/Kolkata"


def institute_timezone(db: Session, institute_id: str) -> ZoneInfo:
    settings = db.get(ScheduleSettings, institute_id)
    name = settings.timezone if settings else DEFAULT_TZ
    try:
        return ZoneInfo(name)
    except Exception:
        return ZoneInfo(DEFAULT_TZ)


def institute_local_date(db: Session, institute_id: str) -> date:
    tz = institute_timezone(db, institute_id)
    return datetime.now(tz).date()
