from datetime import date

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.models import (
    Assignment,
    AttendanceRecord,
    Branch,
    DailyNote,
    Section,
    SectionMember,
    SectionSubject,
    SectionSubjectStudentAssignment,
    Submission,
    TeacherAbsence,
    TeacherSubjectAssignment,
    TimetableEntry,
    TimetableSubstitution,
)
from app.roles import MANAGE_ROLES, PARENT_ROLE, STUDENT_ROLE, TEACHER_ROLES, TEACHING_STAFF_ROLES

VIEW_ALL_SECTIONS_ROLES = MANAGE_ROLES | frozenset({"principal"})
from app.services.institutes import get_member_profile, get_membership, require_membership
from app.services.user_identity import enrich_rows


def _section_row(db: Session, section: Section, member_type: str | None = None) -> dict:
    branch_name = None
    if section.branch_id:
        branch = db.get(Branch, section.branch_id)
        branch_name = branch.name if branch else None
    row = {
        "id": section.id,
        "name": section.name,
        "className": section.class_name,
        "branchId": section.branch_id,
        "branchName": branch_name,
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
    if member.role in VIEW_ALL_SECTIONS_ROLES:
        return True
    if member.role == STUDENT_ROLE:
        enrolled = db.scalar(
            select(SectionMember).where(
                SectionMember.section_id == section_id,
                SectionMember.user_id == user_id,
                SectionMember.member_type == "student",
            )
        )
        return enrolled is not None
    if member.role == PARENT_ROLE:
        return False
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
        select(Section, SectionMember.member_type)
        .join(SectionMember, SectionMember.section_id == Section.id)
        .where(
            Section.institute_id == institute_id,
            SectionMember.user_id == user_id,
        )
        .order_by(Section.name)
    )
    return [_section_row(db, section, member_type) for section, member_type in rows]


def assign_section_member(
    db: Session,
    section_id: str,
    user_id: str,
    member_type: str,
) -> SectionMember:
    if member_type not in ("teacher", "student"):
        raise ValueError("memberType must be teacher or student")

    section = db.get(Section, section_id)
    if not section:
        raise ValueError("Section not found")

    institute_member = get_membership(db, section.institute_id, user_id)
    if not institute_member:
        raise ValueError("User is not an institute member")

    if member_type == "teacher" and institute_member.role not in TEACHING_STAFF_ROLES:
        raise ValueError("User must be teaching staff")
    if member_type == "student" and institute_member.role != "student":
        raise ValueError("User must be a student")

    existing = db.scalar(
        select(SectionMember).where(
            SectionMember.section_id == section_id,
            SectionMember.user_id == user_id,
            SectionMember.member_type == member_type,
        )
    )
    if existing:
        return existing

    if member_type == "student":
        old_memberships = list(
            db.scalars(
                select(SectionMember)
                .join(Section, Section.id == SectionMember.section_id)
                .where(
                    Section.institute_id == section.institute_id,
                    SectionMember.user_id == user_id,
                    SectionMember.member_type == "student",
                    SectionMember.section_id != section_id,
                )
            )
        )
        for old_membership in old_memberships:
            db.execute(
                delete(SectionSubjectStudentAssignment).where(
                    SectionSubjectStudentAssignment.section_id == old_membership.section_id,
                    SectionSubjectStudentAssignment.student_id == user_id,
                )
            )
            db.delete(old_membership)

    row = SectionMember(section_id=section_id, user_id=user_id, member_type=member_type)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def delete_section(db: Session, institute_id: str, section_id: str) -> None:
    section = db.scalar(
        select(Section).where(Section.id == section_id, Section.institute_id == institute_id)
    )
    if not section:
        raise ValueError("Section not found")

    assignment_ids = db.scalars(
        select(Assignment.id).where(Assignment.section_id == section_id)
    ).all()
    for assignment_id in assignment_ids:
        db.execute(delete(Submission).where(Submission.assignment_id == assignment_id))
    db.execute(delete(Assignment).where(Assignment.section_id == section_id))
    db.execute(delete(DailyNote).where(DailyNote.section_id == section_id))
    db.execute(delete(TimetableEntry).where(TimetableEntry.section_id == section_id))
    db.execute(delete(TeacherSubjectAssignment).where(TeacherSubjectAssignment.section_id == section_id))
    db.execute(
        delete(SectionSubjectStudentAssignment).where(
            SectionSubjectStudentAssignment.section_id == section_id
        )
    )
    db.execute(delete(SectionSubject).where(SectionSubject.section_id == section_id))
    db.execute(delete(SectionMember).where(SectionMember.section_id == section_id))
    db.delete(section)
    db.commit()


def bulk_assign_section_members(
    db: Session,
    section_id: str,
    members: list[dict],
) -> dict:
    added = 0
    skipped: list[dict] = []
    for item in members:
        try:
            assign_section_member(db, section_id, item["userId"], item["memberType"])
            added += 1
        except ValueError as error:
            skipped.append({"userId": item["userId"], "reason": str(error)})
    return {"added": added, "skipped": skipped}


def transfer_student_enrollment(
    db: Session,
    institute_id: str,
    student_id: str,
    to_section_id: str,
    reason: str = "",
) -> dict:
    to_section = db.get(Section, to_section_id)
    if not to_section or to_section.institute_id != institute_id:
        raise ValueError("Section not found")

    from_section_id = db.scalar(
        select(SectionMember.section_id)
        .join(Section, Section.id == SectionMember.section_id)
        .where(
            Section.institute_id == institute_id,
            SectionMember.user_id == student_id,
            SectionMember.member_type == "student",
        )
    )
    if from_section_id == to_section_id:
        raise ValueError("Student is already in this section")

    assign_section_member(db, to_section_id, student_id, "student")
    return {
        "studentId": student_id,
        "fromSectionId": from_section_id,
        "toSectionId": to_section_id,
        "reason": reason,
    }


def set_section_class_teacher(
    db: Session, institute_id: str, section_id: str, teacher_user_id: str | None
) -> Section:
    section = db.get(Section, section_id)
    if not section or section.institute_id != institute_id:
        raise ValueError("Section not found")
    if teacher_user_id and not _is_section_teacher(db, section_id, teacher_user_id):
        raise ValueError("Class teacher must be assigned to this section as a teacher")
    section.class_teacher_user_id = teacher_user_id
    db.commit()
    db.refresh(section)
    return section


def remove_section_member(db: Session, section_id: str, user_id: str) -> None:
    section = db.get(Section, section_id)
    if section and section.class_teacher_user_id == user_id:
        section.class_teacher_user_id = None
    db.execute(
        delete(SectionSubjectStudentAssignment).where(
            SectionSubjectStudentAssignment.section_id == section_id,
            SectionSubjectStudentAssignment.student_id == user_id,
        )
    )
    db.execute(
        delete(SectionMember).where(
            SectionMember.section_id == section_id,
            SectionMember.user_id == user_id,
        )
    )
    db.commit()


def _is_section_teacher(db: Session, section_id: str, user_id: str) -> bool:
    return bool(
        db.scalar(
            select(SectionMember).where(
                SectionMember.section_id == section_id,
                SectionMember.user_id == user_id,
                SectionMember.member_type == "teacher",
            )
        )
    )


def can_take_attendance_today(db: Session, section: Section, user_id: str) -> bool:
    member = get_membership(db, section.institute_id, user_id)
    if member and member.role in MANAGE_ROLES:
        return True
    if section.class_teacher_user_id:
        return section.class_teacher_user_id == user_id
    return _is_section_teacher(db, section.id, user_id)


def can_edit_past_attendance(db: Session, section: Section, user_id: str) -> bool:
    member = get_membership(db, section.institute_id, user_id)
    return bool(member and member.role in MANAGE_ROLES)


def assert_can_mark_attendance(
    db: Session, section: Section, user_id: str, attendance_date: date
) -> None:
    today = date.today()
    if attendance_date > today:
        raise PermissionError("Cannot mark attendance for a future date")
    if attendance_date < today:
        if not can_edit_past_attendance(db, section, user_id):
            raise PermissionError(
                "Only the school owner or admin can update attendance for previous days"
            )
        return
    if not can_take_attendance_today(db, section, user_id):
        raise PermissionError("Only the class teacher can take attendance for today")


def attendance_mark_permissions(db: Session, section: Section, user_id: str) -> dict:
    return {
        "canEditPastAttendance": can_edit_past_attendance(db, section, user_id),
        "canTakeAttendanceToday": can_take_attendance_today(db, section, user_id),
    }


def _is_subject_teacher_for_section(db: Session, section_id: str, user_id: str) -> bool:
    return bool(
        db.scalar(
            select(TeacherSubjectAssignment.id).where(
                TeacherSubjectAssignment.section_id == section_id,
                TeacherSubjectAssignment.teacher_id == user_id,
            )
        )
    )


def _is_substitute_for_section_today(
    db: Session, section: Section, user_id: str, on_date: date
) -> bool:
    """Substitute assigned when the class teacher (or period teacher) is on leave."""
    period_sub = db.scalar(
        select(TimetableSubstitution).where(
            TimetableSubstitution.institute_id == section.institute_id,
            TimetableSubstitution.section_id == section.id,
            TimetableSubstitution.substitution_date == on_date,
            TimetableSubstitution.substitute_teacher_id == user_id,
        )
    )
    if period_sub:
        return True
    class_teacher_id = section.class_teacher_user_id
    if not class_teacher_id:
        return False
    absence = db.scalar(
        select(TeacherAbsence).where(
            TeacherAbsence.institute_id == section.institute_id,
            TeacherAbsence.teacher_id == class_teacher_id,
            TeacherAbsence.absence_date == on_date,
        )
    )
    return bool(absence and absence.substitute_teacher_id == user_id)


def can_edit_daily_notes(
    db: Session, section: Section, user_id: str, note_date: date | None = None
) -> bool:
    """Subject teachers (and substitutes) may edit today's section note; admins/students read-only."""
    target = note_date or date.today()
    if target != date.today():
        return False
    member = get_membership(db, section.institute_id, user_id)
    if not member or member.role in VIEW_ALL_SECTIONS_ROLES:
        return False
    if member.role not in {"teacher", "lecturer", "professor"}:
        return False
    if section.class_teacher_user_id == user_id:
        return True
    if _is_subject_teacher_for_section(db, section.id, user_id):
        return True
    if _is_substitute_for_section_today(db, section, user_id, target):
        return True
    return False


def require_daily_note_editor(db: Session, section_id: str, user_id: str) -> Section:
    section = require_section_access(db, section_id, user_id)
    if not can_edit_daily_notes(db, section, user_id):
        raise PermissionError(
            "Only a teacher assigned to a subject in this class (or today's substitute) can edit daily notes"
        )
    return section


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
    assignment_type = db.scalar(
        select(SectionMember.member_type).where(
            SectionMember.section_id == section_id,
            SectionMember.user_id == user_id,
        )
    )
    can_view_roster = institute_member and (
        institute_member.role in MANAGE_ROLES or assignment_type == "teacher"
    )

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
                "assignmentType": assignment.assignment_type,
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
        "classTeacherUserId": section.class_teacher_user_id,
        "canEditDailyNotes": can_edit_daily_notes(db, section, user_id),
        "teacherCount": len(teachers),
        "studentCount": enrolled_students,
        "notesCount": notes_count,
        "averageCompletionPercent": avg_completion,
        "assignments": assignment_rows,
    }
    if can_view_roster:
        overview["students"] = enrich_rows([{"userId": s.user_id} for s in students])
        overview["teachers"] = enrich_rows([{"userId": t.user_id} for t in teachers])
    return overview


def get_student_insights(db: Session, section_id: str, user_id: str) -> list[dict]:
    require_section_teacher(db, section_id, user_id)
    students = list(
        db.scalars(
            select(SectionMember).where(
                SectionMember.section_id == section_id,
                SectionMember.member_type == "student",
            )
        )
    )
    assignments = list(
        db.scalars(select(Assignment).where(Assignment.section_id == section_id))
    )
    rows = []
    for student in students:
        completed = sum(
            1
            for assignment in assignments
            if db.scalar(
                select(Submission.id).where(
                    Submission.assignment_id == assignment.id,
                    Submission.student_id == student.user_id,
                )
            )
        )
        attendance = list(
            db.scalars(
                select(AttendanceRecord).where(
                    AttendanceRecord.section_id == section_id,
                    AttendanceRecord.student_id == student.user_id,
                )
            )
        )
        counts = {status: 0 for status in ("present", "absent", "late", "excused")}
        for record in attendance:
            counts[record.status] = counts.get(record.status, 0) + 1
        marked = sum(counts.values())
        rows.append(
            {
                **enrich_rows([{"userId": student.user_id}])[0],
                "performancePercent": round(completed * 100 / len(assignments))
                if assignments
                else None,
                "attendance": {
                    **counts,
                    "marked": marked,
                    "attendancePercent": round(
                        (counts["present"] + counts["late"]) * 100 / marked
                    )
                    if marked
                    else None,
                },
            }
        )
    return rows


def get_student_performance(
    db: Session, section_id: str, student_id: str, user_id: str
) -> dict:
    require_section_teacher(db, section_id, user_id)
    _require_student(db, section_id, student_id)
    assignments = list(
        db.scalars(
            select(Assignment)
            .where(Assignment.section_id == section_id)
            .order_by(Assignment.due_date.desc().nulls_last())
        )
    )
    records = []
    for assignment in assignments:
        submitted = db.scalar(
            select(Submission.id).where(
                Submission.assignment_id == assignment.id,
                Submission.student_id == student_id,
            )
        )
        year = str(assignment.due_date.year) if assignment.due_date else "Undated"
        records.append(
            {
                "assignmentId": assignment.id,
                "title": assignment.title,
                "type": assignment.assignment_type,
                "academicYear": year,
                "date": assignment.due_date.isoformat() if assignment.due_date else None,
                "percentage": 100 if submitted else 0,
                "submitted": bool(submitted),
            }
        )
    return {
        "studentId": student_id,
        "overallPercent": round(
            sum(item["percentage"] for item in records) / len(records)
        )
        if records
        else None,
        "academicYears": sorted({item["academicYear"] for item in records}, reverse=True),
        "records": records,
    }


def get_student_attendance(
    db: Session,
    section_id: str,
    student_id: str,
    user_id: str,
    start_date,
    end_date,
) -> dict:
    require_section_teacher(db, section_id, user_id)
    _require_student(db, section_id, student_id)
    records = list(
        db.scalars(
            select(AttendanceRecord)
            .where(
                AttendanceRecord.section_id == section_id,
                AttendanceRecord.student_id == student_id,
                AttendanceRecord.attendance_date >= start_date,
                AttendanceRecord.attendance_date <= end_date,
            )
            .order_by(AttendanceRecord.attendance_date)
        )
    )
    counts = {status: 0 for status in ("present", "absent", "late", "excused")}
    output = []
    for record in records:
        counts[record.status] = counts.get(record.status, 0) + 1
        output.append({"date": record.attendance_date.isoformat(), "status": record.status})
    from app.services.student_leave import list_student_leave_in_range  # noqa: PLC0415

    leave_requests = list_student_leave_in_range(
        db, section_id, student_id, user_id, start_date, end_date
    )
    return {
        "studentId": student_id,
        "summary": counts,
        "records": output,
        "leaveRequests": leave_requests,
    }


def _require_student(db: Session, section_id: str, student_id: str) -> None:
    if not db.scalar(
        select(SectionMember).where(
            SectionMember.section_id == section_id,
            SectionMember.user_id == student_id,
            SectionMember.member_type == "student",
        )
    ):
        raise ValueError("Student is not assigned to this section")
