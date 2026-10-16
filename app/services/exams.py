from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models import Exam, InstituteMember, MarkEntry, SectionMember
from app.roles import MANAGE_ROLES, TEACHING_STAFF_ROLES
from app.services.institutes import get_membership, require_membership


def _can_manage_exams(member: InstituteMember) -> bool:
    return member.role in MANAGE_ROLES or member.role == "principal"


def _can_enter_marks(db: Session, exam: Exam, user_id: str, member: InstituteMember) -> bool:
    if _can_manage_exams(member):
        return True
    if member.role not in TEACHING_STAFF_ROLES:
        return False
    if exam.section_id:
        return db.scalar(
            select(SectionMember).where(
                SectionMember.section_id == exam.section_id,
                SectionMember.user_id == user_id,
                SectionMember.member_type == "teacher",
            )
        ) is not None
    return True


def list_exams(db: Session, institute_id: str, user_id: str) -> list[Exam]:
    member = require_membership(db, institute_id, user_id)
    stmt = select(Exam).where(Exam.institute_id == institute_id).order_by(Exam.scheduled_at.desc().nullslast())
    if member.role == "student":
        stmt = stmt.where(Exam.status == "published")
    elif member.role not in MANAGE_ROLES and member.role not in TEACHING_STAFF_ROLES and member.role != "principal":
        raise PermissionError("Staff or student access required")
    return list(db.scalars(stmt))


def get_exam(db: Session, exam_id: str, user_id: str) -> Exam:
    exam = db.get(Exam, exam_id)
    if not exam:
        raise ValueError("Exam not found")
    member = require_membership(db, exam.institute_id, user_id)
    if exam.status != "published" and member.role == "student":
        raise PermissionError("Results not published")
    if exam.status != "published" and member.role not in MANAGE_ROLES and member.role not in TEACHING_STAFF_ROLES and member.role != "principal":
        raise PermissionError("Staff access required")
    return exam


def create_exam(db: Session, institute_id: str, user_id: str, **fields) -> Exam:
    member = require_membership(db, institute_id, user_id)
    if not _can_manage_exams(member):
        raise PermissionError("Owner, admin, or principal role required")
    exam = Exam(institute_id=institute_id, created_by=user_id, **fields)
    db.add(exam)
    db.commit()
    db.refresh(exam)
    return exam


def update_exam(db: Session, exam_id: str, user_id: str, **fields) -> Exam:
    exam = get_exam(db, exam_id, user_id)
    member = get_membership(db, exam.institute_id, user_id)
    if not member or not _can_manage_exams(member):
        raise PermissionError("Owner, admin, or principal role required")
    if exam.status == "published":
        raise ValueError("Cannot edit a published exam")
    for key, value in fields.items():
        if value is not None and hasattr(exam, key):
            setattr(exam, key, value)
    db.commit()
    db.refresh(exam)
    return exam


def delete_exam(db: Session, exam_id: str, user_id: str) -> None:
    exam = get_exam(db, exam_id, user_id)
    member = get_membership(db, exam.institute_id, user_id)
    if not member or not _can_manage_exams(member):
        raise PermissionError("Owner, admin, or principal role required")
    if exam.status == "published":
        raise ValueError("Cannot delete a published exam")
    db.execute(delete(MarkEntry).where(MarkEntry.exam_id == exam_id))
    db.delete(exam)
    db.commit()


def list_marks(db: Session, exam_id: str, user_id: str) -> list[MarkEntry]:
    exam = get_exam(db, exam_id, user_id)
    member = get_membership(db, exam.institute_id, user_id)
    if not member:
        raise PermissionError("Not a member")
    if exam.status != "published":
        if member.role == "student":
            raise PermissionError("Results not published")
        if not _can_enter_marks(db, exam, user_id, member):
            raise PermissionError("Not allowed to view marks for this exam")
    stmt = select(MarkEntry).where(MarkEntry.exam_id == exam_id)
    if member.role == "student":
        stmt = stmt.where(MarkEntry.student_id == user_id)
    return list(db.scalars(stmt.order_by(MarkEntry.student_id)))


def upsert_marks(db: Session, exam_id: str, user_id: str, entries: list[dict]) -> list[MarkEntry]:
    exam = db.get(Exam, exam_id)
    if not exam:
        raise ValueError("Exam not found")
    member = require_membership(db, exam.institute_id, user_id)
    if exam.status == "published":
        raise ValueError("Marks are locked for published exams")
    if not _can_enter_marks(db, exam, user_id, member):
        raise PermissionError("Not allowed to enter marks for this exam")
    saved: list[MarkEntry] = []
    for row in entries:
        subject_id = row.get("subjectId") or exam.subject_id
        existing = db.scalar(
            select(MarkEntry).where(
                MarkEntry.exam_id == exam_id,
                MarkEntry.student_id == row["studentId"],
                MarkEntry.subject_id == subject_id,
            )
        )
        if existing:
            existing.marks_obtained = row.get("marksObtained")
            existing.remarks = row.get("remarks") or ""
            saved.append(existing)
        else:
            entry = MarkEntry(
                exam_id=exam_id,
                student_id=row["studentId"],
                subject_id=subject_id,
                marks_obtained=row.get("marksObtained"),
                remarks=row.get("remarks") or "",
            )
            db.add(entry)
            saved.append(entry)
    db.commit()
    for entry in saved:
        db.refresh(entry)
    return saved


def publish_exam(db: Session, exam_id: str, user_id: str) -> Exam:
    exam = db.get(Exam, exam_id)
    if not exam:
        raise ValueError("Exam not found")
    member = require_membership(db, exam.institute_id, user_id)
    if not _can_manage_exams(member):
        raise PermissionError("Owner, admin, or principal role required")
    exam.status = "published"
    db.commit()
    db.refresh(exam)
    return exam


def exam_to_dict(exam: Exam) -> dict:
    return {
        "id": exam.id,
        "instituteId": exam.institute_id,
        "academicYearId": exam.academic_year_id,
        "sectionId": exam.section_id,
        "subjectId": exam.subject_id,
        "name": exam.name,
        "maxMarks": exam.max_marks,
        "scheduledAt": exam.scheduled_at,
        "status": exam.status,
        "createdBy": exam.created_by,
        "createdAt": exam.created_at,
    }


def mark_to_dict(entry: MarkEntry) -> dict:
    return {
        "id": entry.id,
        "examId": entry.exam_id,
        "studentId": entry.student_id,
        "subjectId": entry.subject_id,
        "marksObtained": entry.marks_obtained,
        "remarks": entry.remarks,
    }
