from sqlalchemy import select
from sqlalchemy.orm import Session

from app.grade_bands import GRADE_BANDS
from app.models import Class, Section


def list_classes(db: Session, institute_id: str) -> list[Class]:
    return list(
        db.scalars(
            select(Class).where(Class.institute_id == institute_id).order_by(Class.name)
        )
    )


def get_class(db: Session, institute_id: str, class_id: str) -> Class:
    row = db.scalar(select(Class).where(Class.id == class_id, Class.institute_id == institute_id))
    if not row:
        raise ValueError("Class not found")
    return row


def create_class(db: Session, institute_id: str, name: str, grade_band: str) -> Class:
    label = " ".join(name.split()) or "Unnamed class"
    if grade_band not in GRADE_BANDS:
        raise ValueError("Invalid grade band")
    existing = db.scalar(
        select(Class).where(Class.institute_id == institute_id, Class.name == label)
    )
    if existing:
        raise ValueError("A class with that name already exists")
    row = Class(institute_id=institute_id, name=label, grade_band=grade_band)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def get_or_create_class(db: Session, institute_id: str, name: str, grade_band: str) -> Class:
    label = " ".join(name.split()) or "Unnamed class"
    if grade_band not in GRADE_BANDS:
        raise ValueError("Invalid grade band")
    existing = db.scalar(
        select(Class).where(Class.institute_id == institute_id, Class.name == label)
    )
    if existing:
        if existing.grade_band != grade_band:
            raise ValueError("This class already uses a different grade band")
        return existing
    row = Class(institute_id=institute_id, name=label, grade_band=grade_band)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def update_class(
    db: Session, institute_id: str, class_id: str, name: str | None, grade_band: str | None
) -> Class:
    row = get_class(db, institute_id, class_id)
    if name is not None:
        label = " ".join(name.split()) or "Unnamed class"
        clash = db.scalar(
            select(Class).where(
                Class.institute_id == institute_id,
                Class.name == label,
                Class.id != class_id,
            )
        )
        if clash:
            raise ValueError("A class with that name already exists")
        row.name = label
    if grade_band is not None:
        if grade_band not in GRADE_BANDS:
            raise ValueError("Invalid grade band")
        row.grade_band = grade_band
    for section in db.scalars(select(Section).where(Section.class_id == row.id)):
        section.class_name = row.name
        section.grade_band = row.grade_band
    db.commit()
    db.refresh(row)
    return row


def delete_class(db: Session, institute_id: str, class_id: str) -> None:
    row = get_class(db, institute_id, class_id)
    has_section = db.scalar(select(Section.id).where(Section.class_id == row.id))
    if has_section:
        raise ValueError("Remove sections before deleting the class")
    db.delete(row)
    db.commit()


def create_section(
    db: Session,
    institute_id: str,
    class_id: str,
    name: str,
    branch_id: str | None,
) -> Section:
    row = get_class(db, institute_id, class_id)
    label = " ".join(name.split())
    if not label:
        raise ValueError("Section name is required")
    section = Section(
        institute_id=institute_id,
        class_id=row.id,
        name=label,
        class_name=row.name,
        grade_band=row.grade_band,
        branch_id=branch_id,
    )
    db.add(section)
    db.commit()
    db.refresh(section)
    return section
