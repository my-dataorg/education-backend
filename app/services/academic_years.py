from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AcademicTerm, AcademicYear
from app.services.institutes import require_manage


def _default_dates() -> tuple[date, date]:
    year = date.today().year
    if date.today().month < 4:
        year -= 1
    return date(year, 4, 1), date(year + 1, 3, 31)


def get_active_academic_year_bounds(db: Session, institute_id: str) -> tuple[date, date, str]:
    """Read-only active year range for teachers (no auto-create)."""
    year = db.scalar(
        select(AcademicYear)
        .where(AcademicYear.institute_id == institute_id, AcademicYear.is_active.is_(True))
        .order_by(AcademicYear.start_date.desc())
    )
    if year:
        return year.start_date, year.end_date, year.label
    start_date, end_date = _default_dates()
    return start_date, end_date, f"{start_date.year}-{str(end_date.year)[-2:]}"


def get_or_create_active(db: Session, institute_id: str, user_id: str) -> AcademicYear:
    require_manage(db, institute_id, user_id)
    year = db.scalar(
        select(AcademicYear)
        .where(AcademicYear.institute_id == institute_id, AcademicYear.is_active.is_(True))
        .order_by(AcademicYear.start_date.desc())
    )
    if year:
        return year
    start_date, end_date = _default_dates()
    year = AcademicYear(
        institute_id=institute_id,
        label=f"{start_date.year}-{str(end_date.year)[-2:]}",
        start_date=start_date,
        end_date=end_date,
    )
    db.add(year)
    db.flush()
    db.add_all(
        [
            AcademicTerm(
                academic_year_id=year.id,
                name="Term 1",
                start_date=start_date,
                end_date=date(start_date.year, 9, 30),
                weight_percent=50,
            ),
            AcademicTerm(
                academic_year_id=year.id,
                name="Term 2",
                start_date=date(start_date.year, 10, 1),
                end_date=end_date,
                weight_percent=50,
            ),
        ]
    )
    db.commit()
    db.refresh(year)
    return year


def update_active(
    db: Session, institute_id: str, user_id: str, values: dict
) -> AcademicYear:
    year = get_or_create_active(db, institute_id, user_id)
    for key, value in values.items():
        setattr(year, key, value)
    db.commit()
    db.refresh(year)
    return year


def terms(db: Session, year_id: str) -> list[AcademicTerm]:
    return list(
        db.scalars(
            select(AcademicTerm)
            .where(AcademicTerm.academic_year_id == year_id)
            .order_by(AcademicTerm.start_date)
        )
    )
