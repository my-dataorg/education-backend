from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import InstituteRoom, PublishedTimetableEntry, TimetableEntry, TimetableSchoolDefault


def list_rooms(db: Session, institute_id: str) -> list[InstituteRoom]:
    return list(
        db.scalars(
            select(InstituteRoom)
            .where(InstituteRoom.institute_id == institute_id)
            .order_by(InstituteRoom.name)
        )
    )


def create_room(db: Session, institute_id: str, name: str) -> InstituteRoom:
    cleaned = name.strip()[:30]
    if not cleaned:
        raise ValueError("Room name is required")
    room = InstituteRoom(institute_id=institute_id, name=cleaned)
    db.add(room)
    try:
        db.commit()
    except IntegrityError as error:
        db.rollback()
        raise ValueError("Room already exists") from error
    db.refresh(room)
    return room


def delete_room(db: Session, institute_id: str, room_id: str) -> None:
    room = db.scalar(
        select(InstituteRoom).where(
            InstituteRoom.id == room_id,
            InstituteRoom.institute_id == institute_id,
        )
    )
    if not room:
        raise ValueError("Room not found")
    if db.scalar(
        select(TimetableEntry.id).where(
            TimetableEntry.institute_id == institute_id,
            TimetableEntry.room == room.name,
        )
    ):
        raise ValueError("Room is used in the timetable")
    if db.scalar(
        select(PublishedTimetableEntry.id).where(
            PublishedTimetableEntry.institute_id == institute_id,
            PublishedTimetableEntry.room == room.name,
        )
    ):
        raise ValueError("Room is used in the published timetable")
    if db.scalar(
        select(TimetableSchoolDefault.id).where(
            TimetableSchoolDefault.institute_id == institute_id,
            TimetableSchoolDefault.room == room.name,
        )
    ):
        raise ValueError("Room is used in the school default timetable")
    db.execute(delete(InstituteRoom).where(InstituteRoom.id == room_id))
    db.commit()
