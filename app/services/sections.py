from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.models import Assignment, Branch, DailyNote, Section, SectionMember, Subject, Submission, TeacherSubject
from app.roles import MANAGE_ROLES, TEACHER_ROLES
from app.services.grade_bands import list_teacher_grade_bands
from app.services.institutes import get_member_profile, get_membership, require_membership
from app.services.user_identity import enrich_rows


def _section_row(
    db: Session,
    section: Section,
    member_type: str | None = None,
    subject_names: list[str] | None = None,
) -> dict:
    branch_name = None
    if section.branch_id:
        branch = db.get(Branch, section.branch_id)
        branch_name = branch.name if branch else None
    row = {
        "id": section.id,
        "name": section.name,
        "className": section.class_name,
        "classId": section.class_id,
        "gradeBand": section.grade_band,
        "branchId": section.branch_id,
        "branchName": branch_name,
        "subjectNames": subject_names or [],
    }
    if member_type:
        row["memberType"] = member_type
    return row


def user_can_access_section(db: Session, section_id: str, user_id: str) -> bool:
    section = db.get(Section, section_id)
    if not section:
        return False
    member = get_membership(db, section.institute_id, user_id)
    if not member:
        return False
    if member.role in MANAGE_ROLES:
        return True
    enrolled = db.scalar(
        select(SectionMember).where(
            SectionMember.section_id == section_id,
            SectionMember.user_id == user_id,
        )
    )
    return enrolled is not None


def require_section_access(db: Session, section_id: str, user_id: str) -> Section:
    section = db.get(Section, section_id)
    if not section:
        raise ValueError("Section not found")
    if not user_can_access_section(db, section_id, user_id):
        raise PermissionError("Not enrolled in this section")
    return section


def list_member_sections(db: Session, institute_id: str, member_user_id: str) -> list[dict]:
    profile = get_member_profile(db, institute_id, member_user_id)
    return profile["sections"]


def list_my_enrolled_sections(db: Session, institute_id: str, user_id: str) -> list[dict]:
    require_membership(db, institute_id, user_id)
    rows = db.execute(
        select(Section, SectionMember.member_type, Subject.name)
        .join(SectionMember, SectionMember.section_id == Section.id)
        .outerjoin(Subject, Subject.id == SectionMember.subject_id)
        .where(
            Section.institute_id == institute_id,
            SectionMember.user_id == user_id,
        )
        .order_by(Section.name)
    )
    grouped: dict[str, dict] = {}
    for section, member_type, subject_name in rows:
        item = grouped.get(section.id)
        if not item:
            item = _section_row(db, section, member_type, [])
            grouped[section.id] = item
        if subject_name and subject_name not in item["subjectNames"]:
            item["subjectNames"].append(subject_name)
    return list(grouped.values())


def assign_section_member(
    db: Session,
    section_id: str,
    user_id: str,
    member_type: str,
    subject_id: str | None = None,
) -> SectionMember:
    if member_type not in ("teacher", "student"):
        raise ValueError("memberType must be teacher or student")

    section = db.get(Section, section_id)
    if not section:
        raise ValueError("Section not found")

    institute_member = get_membership(db, section.institute_id, user_id)
    if not institute_member:
        raise ValueError("User is not an institute member")

    if member_type == "teacher" and institute_member.role not in TEACHER_ROLES:
        raise ValueError("User must be teaching staff")

    if member_type == "student":
        existing = db.scalar(
            select(SectionMember).where(
                SectionMember.section_id == section_id,
                SectionMember.user_id == user_id,
                SectionMember.member_type == "student",
            )
        )
        if existing:
            return existing
        row = SectionMember(section_id=section_id, user_id=user_id, member_type="student")
        db.add(row)
        db.commit()
        db.refresh(row)
        return row

    if not subject_id:
        raise ValueError("subjectId is required for a teacher")
    subject = db.scalar(
        select(Subject).where(Subject.id == subject_id, Subject.institute_id == section.institute_id)
    )
    if not subject:
        raise ValueError("Subject not found")
    qualified = db.scalar(
        select(TeacherSubject).where(
            TeacherSubject.institute_id == section.institute_id,
            TeacherSubject.user_id == user_id,
            TeacherSubject.subject_id == subject_id,
        )
    )
    if not qualified:
        raise ValueError("Teacher is not assigned that subject")
    bands = list_teacher_grade_bands(db, section.institute_id, user_id)
    if section.grade_band not in bands:
        raise ValueError("Teacher is not assigned that grade band")
    taken = db.scalar(
        select(SectionMember).where(
            SectionMember.section_id == section_id,
            SectionMember.member_type == "teacher",
            SectionMember.subject_id == subject_id,
        )
    )
    if taken:
        if taken.user_id == user_id:
            return taken
        raise ValueError("That subject already has a teacher in this section")

    existing = db.scalar(
        select(SectionMember).where(
            SectionMember.section_id == section_id,
            SectionMember.user_id == user_id,
            SectionMember.member_type == "teacher",
            SectionMember.subject_id == subject_id,
        )
    )
    if existing:
        return existing

    row = SectionMember(
        section_id=section_id,
        user_id=user_id,
        member_type="teacher",
        subject_id=subject_id,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def remove_section_member(db: Session, section_id: str, user_id: str, subject_id: str | None = None) -> None:
    stmt = delete(SectionMember).where(
        SectionMember.section_id == section_id,
        SectionMember.user_id == user_id,
    )
    if subject_id:
        stmt = stmt.where(SectionMember.subject_id == subject_id)
    db.execute(stmt)
    db.commit()


def require_section_teacher(db: Session, section_id: str, user_id: str) -> Section:
    section = require_section_access(db, section_id, user_id)
    member = get_membership(db, section.institute_id, user_id)
    if not member:
        raise PermissionError("Not a member")
    if member.role in MANAGE_ROLES:
        return section
    if member.role not in TEACHER_ROLES:
        raise PermissionError("Teacher role required")
    enrolled = db.scalar(
        select(SectionMember).where(
            SectionMember.section_id == section_id,
            SectionMember.user_id == user_id,
            SectionMember.member_type == "teacher",
        )
    )
    if not enrolled:
        raise PermissionError("Not assigned to this section")
    return section


def require_section_subject_teacher(
    db: Session, section_id: str, user_id: str, subject_id: str
) -> Section:
    section = require_section_teacher(db, section_id, user_id)
    subject = db.get(Subject, subject_id)
    if not subject or subject.institute_id != section.institute_id:
        raise ValueError("Subject not found")
    taught = db.scalar(
        select(SectionMember).where(
            SectionMember.section_id == section_id,
            SectionMember.member_type == "teacher",
            SectionMember.subject_id == subject_id,
        )
    )
    if not taught:
        raise ValueError("That subject is not taught in this section")
    member = get_membership(db, section.institute_id, user_id)
    if member and member.role in MANAGE_ROLES:
        return section
    if taught.user_id != user_id:
        raise PermissionError("Not the teacher of this subject")
    return section


def require_section_student(db: Session, section_id: str, user_id: str) -> Section:
    section = require_section_access(db, section_id, user_id)
    member = get_membership(db, section.institute_id, user_id)
    if not member or member.role != "student":
        raise PermissionError("Student role required")
    enrolled = db.scalar(
        select(SectionMember).where(
            SectionMember.section_id == section_id,
            SectionMember.user_id == user_id,
            SectionMember.member_type == "student",
        )
    )
    if not enrolled:
        raise PermissionError("Not enrolled in this section")
    return section


def get_section_overview(db: Session, section_id: str, user_id: str) -> dict:
    section = require_section_access(db, section_id, user_id)
    institute_member = get_membership(db, section.institute_id, user_id)
    is_teacher_view = institute_member and institute_member.role in TEACHER_ROLES

    students = list(
        db.scalars(
            select(SectionMember).where(
                SectionMember.section_id == section_id,
                SectionMember.member_type == "student",
            )
        )
    )
    teachers = list(
        db.scalars(
            select(SectionMember).where(
                SectionMember.section_id == section_id,
                SectionMember.member_type == "teacher",
            )
        )
    )

    assignments = list(
        db.scalars(
            select(Assignment)
            .where(Assignment.section_id == section_id)
            .order_by(Assignment.due_date.desc().nulls_last())
        )
    )

    assignment_rows = []
    total_completion = 0
    enrolled_students = len(students)
    for assignment in assignments:
        submitted = db.scalar(
            select(func.count())
            .select_from(Submission)
            .where(Submission.assignment_id == assignment.id)
        ) or 0
        pct = round(submitted * 100 / enrolled_students) if enrolled_students else 0
        total_completion += pct
        assignment_rows.append(
            {
                "id": assignment.id,
                "title": assignment.title,
                "description": assignment.description,
                "dueDate": assignment.due_date.isoformat() if assignment.due_date else None,
                "submittedCount": submitted,
                "enrolledStudents": enrolled_students,
                "completionPercent": pct,
            }
        )

    notes_count = db.scalar(
        select(func.count()).select_from(DailyNote).where(DailyNote.section_id == section_id)
    ) or 0

    avg_completion = round(total_completion / len(assignments)) if assignments else None

    overview: dict = {
        "sectionId": section.id,
        "sectionName": section.name,
        "className": section.class_name,
        "teacherCount": len(teachers),
        "studentCount": enrolled_students,
        "notesCount": notes_count,
        "averageCompletionPercent": avg_completion,
        "assignments": assignment_rows,
    }
    if is_teacher_view:
        overview["students"] = enrich_rows([{"userId": s.user_id} for s in students])
        teacher_rows = []
        for t in teachers:
            subject = db.get(Subject, t.subject_id) if t.subject_id else None
            teacher_rows.append(
                {
                    "userId": t.user_id,
                    "subjectId": t.subject_id,
                    "subjectName": subject.name if subject else None,
                }
            )
        overview["teachers"] = enrich_rows(teacher_rows)
    return overview
