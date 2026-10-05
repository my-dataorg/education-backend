from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models import InstituteMember, TeacherAbsence

TEACHER_ROLES = {"teacher", "lecturer", "professor"}


def list_absences(db: Session, institute_id: str, absence_date):
    return list(
        db.scalars(
            select(TeacherAbsence)
            .where(
                TeacherAbsence.institute_id == institute_id,
                TeacherAbsence.absence_date == absence_date,
            )
            .order_by(TeacherAbsence.teacher_id)
        )
    )


def save_absence(db: Session, institute_id: str, body) -> TeacherAbsence:
    teacher = db.scalar(
        select(InstituteMember).where(
            InstituteMember.institute_id == institute_id,
            InstituteMember.user_id == body.teacherId,
            InstituteMember.role.in_(TEACHER_ROLES),
        )
    )
    if not teacher:
        raise ValueError("Teacher is not a member of this institute")
    if body.substituteTeacherId:
        substitute = db.scalar(
            select(InstituteMember).where(
                InstituteMember.institute_id == institute_id,
                InstituteMember.user_id == body.substituteTeacherId,
                InstituteMember.role.in_(TEACHER_ROLES),
            )
        )
        if not substitute:
            raise ValueError("Substitute must be an institute teacher")
        if substitute.user_id == teacher.user_id:
            raise ValueError("Substitute must be a different teacher")

    absence = db.scalar(
        select(TeacherAbsence).where(
            TeacherAbsence.institute_id == institute_id,
            TeacherAbsence.teacher_id == body.teacherId,
            TeacherAbsence.absence_date == body.absenceDate,
        )
    )
    if not absence:
        absence = TeacherAbsence(
            institute_id=institute_id,
            teacher_id=body.teacherId,
            absence_date=body.absenceDate,
        )
        db.add(absence)
    absence.substitute_teacher_id = body.substituteTeacherId
    absence.note = body.note.strip()
    db.commit()
    db.refresh(absence)
    return absence


def remove_absence(db: Session, institute_id: str, absence_id: str) -> None:
    absence = db.scalar(
        select(TeacherAbsence).where(
            TeacherAbsence.id == absence_id,
            TeacherAbsence.institute_id == institute_id,
        )
    )
    if not absence:
        raise ValueError("Teacher absence not found")
    db.execute(delete(TeacherAbsence).where(TeacherAbsence.id == absence_id))
    db.commit()
