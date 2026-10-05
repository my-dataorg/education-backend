from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import Activity, ScheduleSlot

DEFAULT_ACTIVITIES = ("Break", "Play time", "Lunch time")


def ensure_default_activities(db: Session, institute_id: str) -> None:
    existing = set(
        db.scalars(select(Activity.name).where(Activity.institute_id == institute_id))
    )
    missing = [
        Activity(institute_id=institute_id, name=name, is_system=True)
        for name in DEFAULT_ACTIVITIES
        if name not in existing
    ]
    if missing:
        db.add_all(missing)
        db.commit()


def list_activities(db: Session, institute_id: str) -> list[Activity]:
    ensure_default_activities(db, institute_id)
    return list(
        db.scalars(
            select(Activity)
            .where(Activity.institute_id == institute_id)
            .order_by(Activity.name)
        )
    )


def create_activity(db: Session, institute_id: str, name: str) -> Activity:
    activity = Activity(institute_id=institute_id, name=name.strip())
    db.add(activity)
    try:
        db.commit()
    except IntegrityError as error:
        db.rollback()
        raise ValueError("Activity already exists") from error
    db.refresh(activity)
    return activity


def delete_activity(db: Session, institute_id: str, activity_id: str) -> None:
    activity = db.scalar(
        select(Activity).where(
            Activity.id == activity_id,
            Activity.institute_id == institute_id,
        )
    )
    if not activity:
        raise ValueError("Activity not found")
    if activity.is_system:
        raise ValueError("Default activities cannot be deleted")
    if db.scalar(select(ScheduleSlot.id).where(ScheduleSlot.activity_id == activity_id)):
        raise ValueError("Activity is used by a schedule")
    db.execute(delete(Activity).where(Activity.id == activity_id))
    db.commit()


def require_activity(db: Session, institute_id: str, activity_id: str) -> Activity:
    activity = db.scalar(
        select(Activity).where(
            Activity.id == activity_id,
            Activity.institute_id == institute_id,
        )
    )
    if not activity:
        raise ValueError("Activity not found")
    return activity
