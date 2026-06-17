from datetime import date, datetime, timezone

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.models import (
    Assignment,
    Branch,
    DailyNote,
    Institute,
    InstituteInvitation,
    InstituteMember,
    Section,
    SectionMember,
    Submission,
)
from app.roles import MANAGE_ROLES, STAFF_ROLES, STUDENT_ROLE, VIEW_DIRECTORY_ROLES
from app.services.user_identity import enrich_rows


def get_membership(db: Session, institute_id: str, user_id: str) -> InstituteMember | None:
    return db.scalar(
        select(InstituteMember).where(
            InstituteMember.institute_id == institute_id,
            InstituteMember.user_id == user_id,
        )
    )


def require_membership(db: Session, institute_id: str, user_id: str) -> InstituteMember:
    member = get_membership(db, institute_id, user_id)
    if not member:
        raise PermissionError("Not a member of this institute")
    return member


def require_manage(db: Session, institute_id: str, user_id: str) -> InstituteMember:
    member = require_membership(db, institute_id, user_id)
    if member.role not in MANAGE_ROLES:
        raise PermissionError("Owner or admin role required")
    return member


def require_directory_view(db: Session, institute_id: str, user_id: str) -> InstituteMember:
    member = require_membership(db, institute_id, user_id)
    if member.role not in VIEW_DIRECTORY_ROLES:
        raise PermissionError("Staff access required")
    return member


def list_user_institutes(db: Session, user_id: str) -> list[Institute]:
    stmt = (
        select(Institute)
        .join(InstituteMember)
        .where(InstituteMember.user_id == user_id)
        .order_by(Institute.name)
    )
    return list(db.scalars(stmt))


def get_institute_stats(db: Session, institute_id: str) -> dict[str, int]:
    staff_count = db.scalar(
        select(func.count())
        .select_from(InstituteMember)
        .where(
            InstituteMember.institute_id == institute_id,
            InstituteMember.role.in_(STAFF_ROLES),
        )
    )
    student_count = db.scalar(
        select(func.count())
        .select_from(InstituteMember)
        .where(InstituteMember.institute_id == institute_id, InstituteMember.role == STUDENT_ROLE)
    )
    section_count = db.scalar(
        select(func.count()).select_from(Section).where(Section.institute_id == institute_id)
    )
    branch_count = db.scalar(
        select(func.count()).select_from(Branch).where(Branch.institute_id == institute_id)
    )
    return {
        "staffCount": staff_count or 0,
        "studentCount": student_count or 0,
        "sectionCount": section_count or 0,
        "branchCount": branch_count or 0,
    }


def list_members(db: Session, institute_id: str, group: str | None = None) -> list[InstituteMember]:
    stmt = select(InstituteMember).where(InstituteMember.institute_id == institute_id)
    if group == "staff":
        stmt = stmt.where(InstituteMember.role.in_(STAFF_ROLES))
    elif group == "students":
        stmt = stmt.where(InstituteMember.role == STUDENT_ROLE)
    stmt = stmt.order_by(InstituteMember.role, InstituteMember.user_id)
    return list(db.scalars(stmt))


def add_member(db: Session, institute_id: str, user_id: str, role: str) -> InstituteMember:
    existing = get_membership(db, institute_id, user_id)
    if existing:
        raise ValueError("User is already a member")
    member = InstituteMember(institute_id=institute_id, user_id=user_id, role=role)
    db.add(member)
    db.commit()
    db.refresh(member)
    return member


def remove_member(db: Session, institute_id: str, member_user_id: str) -> None:
    member = get_membership(db, institute_id, member_user_id)
    if not member:
        raise ValueError("Member not found")
    if member.role == "owner":
        raise PermissionError("Cannot remove the owner")
    db.delete(member)
    db.commit()


def get_member_profile(db: Session, institute_id: str, member_user_id: str) -> dict:
    member = get_membership(db, institute_id, member_user_id)
    if not member:
        raise ValueError("Member not found")

    sections = db.scalars(
        select(Section)
        .join(SectionMember, SectionMember.section_id == Section.id)
        .where(
            Section.institute_id == institute_id,
            SectionMember.user_id == member_user_id,
        )
    ).all()

    section_details = []
    branch_names: set[str] = set()
    for section in sections:
        branch_name = None
        if section.branch_id:
            branch = db.get(Branch, section.branch_id)
            if branch:
                branch_name = branch.name
                branch_names.add(branch.name)
        sm = db.scalar(
            select(SectionMember).where(
                SectionMember.section_id == section.id,
                SectionMember.user_id == member_user_id,
            )
        )
        section_details.append(
            {
                "sectionId": section.id,
                "sectionName": section.name,
                "className": section.class_name,
                "branchName": branch_name,
                "memberType": sm.member_type if sm else None,
            }
        )

    return {
        "userId": member.user_id,
        "role": member.role,
        "sections": section_details,
        "branches": sorted(branch_names),
    }


def _section_ids_for_branch(
    db: Session,
    institute_id: str,
    branch_id: str,
    primary_id: str | None,
) -> list[str]:
    sections = list(
        db.scalars(select(Section).where(Section.institute_id == institute_id)).all()
    )
    ids: list[str] = []
    for section in sections:
        if section.branch_id == branch_id:
            ids.append(section.id)
        elif section.branch_id is None and primary_id and branch_id == primary_id:
            ids.append(section.id)
    return ids


def _branch_insights(db: Session, section_ids: list[str]) -> dict:
    if not section_ids:
        return {
            "openAssignments": 0,
            "averageCompletionPercent": None,
            "recentResults": [],
        }

    today = date.today()
    assignments = list(
        db.scalars(
            select(Assignment)
            .where(Assignment.section_id.in_(section_ids))
            .order_by(Assignment.due_date.desc().nulls_last(), Assignment.id.desc())
        ).all()
    )
    open_assignments = sum(
        1 for a in assignments if a.due_date is None or a.due_date >= today
    )

    recent_results: list[dict] = []
    completion_rates: list[int] = []

    for assignment in assignments[:8]:
        section = db.get(Section, assignment.section_id)
        if not section:
            continue
        enrolled = db.scalar(
            select(func.count())
            .select_from(SectionMember)
            .where(
                SectionMember.section_id == section.id,
                SectionMember.member_type == "student",
            )
        ) or 0
        submitted = db.scalar(
            select(func.count())
            .select_from(Submission)
            .where(Submission.assignment_id == assignment.id)
        ) or 0
        completion = round(submitted / enrolled * 100) if enrolled else 0
        if enrolled:
            completion_rates.append(completion)
        recent_results.append(
            {
                "assignmentId": assignment.id,
                "title": assignment.title,
                "sectionName": section.name,
                "dueDate": assignment.due_date.isoformat() if assignment.due_date else None,
                "submittedCount": submitted,
                "enrolledStudents": enrolled,
                "completionPercent": completion,
            }
        )

    average = round(sum(completion_rates) / len(completion_rates)) if completion_rates else None

    return {
        "openAssignments": open_assignments,
        "averageCompletionPercent": average,
        "recentResults": recent_results[:5],
    }


def get_institute_summary(db: Session, institute_id: str) -> dict:
    branches = list(
        db.scalars(select(Branch).where(Branch.institute_id == institute_id).order_by(Branch.name))
    )
    primary = next((b for b in branches if b.is_primary), branches[0] if branches else None)

    branch_summaries = []
    for branch in branches:
        section_ids = list(
            db.scalars(select(Section.id).where(Section.branch_id == branch.id)).all()
        )
        teacher_ids: set[str] = set()
        student_ids: set[str] = set()
        for sid in section_ids:
            for sm in db.scalars(select(SectionMember).where(SectionMember.section_id == sid)):
                if sm.member_type == "teacher":
                    teacher_ids.add(sm.user_id)
                else:
                    student_ids.add(sm.user_id)

        teachers = []
        for uid in sorted(teacher_ids):
            m = get_membership(db, institute_id, uid)
            teachers.append({"userId": uid, "role": m.role if m else "teacher"})

        students = []
        for uid in sorted(student_ids):
            m = get_membership(db, institute_id, uid)
            students.append({"userId": uid, "role": m.role if m else "student"})

        branch_summaries.append(
            {
                "id": branch.id,
                "name": branch.name,
                "isPrimary": branch.is_primary,
                "address": branch.address,
                "city": branch.city,
                "teacherCount": len(teacher_ids),
                "studentCount": len(student_ids),
                "teachers": teachers,
                "students": students,
                "insights": _branch_insights(
                    db,
                    _section_ids_for_branch(db, institute_id, branch.id, primary.id if primary else None),
                ),
            }
        )

    # Sections without a branch roll up to primary branch counts
    if primary:
        primary_summary = next((b for b in branch_summaries if b["id"] == primary.id), None)
        if primary_summary:
            extra_teacher_ids = {t["userId"] for t in primary_summary["teachers"]}
            extra_student_ids = {s["userId"] for s in primary_summary["students"]}
            unassigned = list(
                db.scalars(
                    select(Section).where(
                        Section.institute_id == institute_id,
                        Section.branch_id.is_(None),
                    )
                ).all()
            )
            for section in unassigned:
                for sm in db.scalars(
                    select(SectionMember).where(SectionMember.section_id == section.id)
                ):
                    if sm.member_type == "teacher":
                        if sm.user_id not in extra_teacher_ids:
                            m = get_membership(db, institute_id, sm.user_id)
                            primary_summary["teachers"].append(
                                {"userId": sm.user_id, "role": m.role if m else "teacher"}
                            )
                            extra_teacher_ids.add(sm.user_id)
                    elif sm.user_id not in extra_student_ids:
                        m = get_membership(db, institute_id, sm.user_id)
                        primary_summary["students"].append(
                            {"userId": sm.user_id, "role": m.role if m else "student"}
                        )
                        extra_student_ids.add(sm.user_id)
            primary_summary["teacherCount"] = len(primary_summary["teachers"])
            primary_summary["studentCount"] = len(primary_summary["students"])

    today = date.today()
    upcoming = []
    rows = db.execute(
        select(Assignment, Section, Branch)
        .join(Section, Assignment.section_id == Section.id)
        .outerjoin(Branch, Section.branch_id == Branch.id)
        .where(
            Section.institute_id == institute_id,
            Assignment.due_date.is_not(None),
            Assignment.due_date >= today,
        )
        .order_by(Assignment.due_date)
        .limit(10)
    )
    for assignment, section, branch in rows:
        upcoming.append(
            {
                "type": "assignment_due",
                "title": assignment.title,
                "dueDate": assignment.due_date.isoformat(),
                "sectionName": section.name,
                "branchName": branch.name if branch else None,
            }
        )

    pending_invitations = db.scalar(
        select(func.count())
        .select_from(InstituteInvitation)
        .where(
            InstituteInvitation.institute_id == institute_id,
            InstituteInvitation.status == "pending",
        )
    ) or 0

    for branch in branch_summaries:
        branch["teachers"] = enrich_rows(branch["teachers"])
        branch["students"] = enrich_rows(branch["students"])

    return {
        "branchCount": len(branches),
        "branches": branch_summaries,
        "upcomingEvents": upcoming,
        "pendingInvitations": pending_invitations,
    }


def list_branches(db: Session, institute_id: str) -> list[tuple[Branch, int]]:
    branches = list(
        db.scalars(select(Branch).where(Branch.institute_id == institute_id).order_by(Branch.name))
    )
    result: list[tuple[Branch, int]] = []
    for branch in branches:
        count = db.scalar(
            select(func.count()).select_from(Section).where(Section.branch_id == branch.id)
        )
        result.append((branch, count or 0))
    return result


def create_branch(
    db: Session,
    institute_id: str,
    name: str,
    address: str,
    city: str,
    is_primary: bool,
) -> Branch:
    if is_primary:
        for existing in db.scalars(
            select(Branch).where(Branch.institute_id == institute_id, Branch.is_primary.is_(True))
        ):
            existing.is_primary = False
    branch = Branch(
        institute_id=institute_id,
        name=name,
        address=address,
        city=city,
        is_primary=is_primary,
    )
    db.add(branch)
    db.commit()
    db.refresh(branch)
    return branch


def update_branch(
    db: Session,
    institute_id: str,
    branch_id: str,
    *,
    name: str | None = None,
    address: str | None = None,
    city: str | None = None,
    is_primary: bool | None = None,
) -> Branch:
    branch = db.scalar(
        select(Branch).where(Branch.id == branch_id, Branch.institute_id == institute_id)
    )
    if not branch:
        raise ValueError("Branch not found")
    if is_primary:
        for existing in db.scalars(
            select(Branch).where(Branch.institute_id == institute_id, Branch.is_primary.is_(True))
        ):
            existing.is_primary = False
    if name is not None:
        branch.name = name
    if address is not None:
        branch.address = address
    if city is not None:
        branch.city = city
    if is_primary is not None:
        branch.is_primary = is_primary
    db.commit()
    db.refresh(branch)
    return branch


def delete_branch(db: Session, institute_id: str, branch_id: str) -> None:
    branch = db.scalar(
        select(Branch).where(Branch.id == branch_id, Branch.institute_id == institute_id)
    )
    if not branch:
        raise ValueError("Branch not found")
    for section in db.scalars(select(Section).where(Section.branch_id == branch_id)):
        section.branch_id = None
    db.delete(branch)
    db.commit()


def delete_institute(db: Session, institute_id: str, user_id: str) -> None:
    member = get_membership(db, institute_id, user_id)
    if not member or member.role != "owner":
        raise PermissionError("Only the owner can delete this institute")

    inst = db.get(Institute, institute_id)
    if not inst:
        raise ValueError("Institute not found")

    sections = db.scalars(select(Section).where(Section.institute_id == institute_id)).all()
    for section in sections:
        assignment_ids = db.scalars(
            select(Assignment.id).where(Assignment.section_id == section.id)
        ).all()
        for aid in assignment_ids:
            db.execute(delete(Submission).where(Submission.assignment_id == aid))
        db.execute(delete(Assignment).where(Assignment.section_id == section.id))
        db.execute(delete(DailyNote).where(DailyNote.section_id == section.id))
        db.execute(delete(SectionMember).where(SectionMember.section_id == section.id))

    db.execute(delete(Section).where(Section.institute_id == institute_id))
    db.execute(delete(InstituteInvitation).where(InstituteInvitation.institute_id == institute_id))
    db.execute(delete(Branch).where(Branch.institute_id == institute_id))
    db.execute(delete(InstituteMember).where(InstituteMember.institute_id == institute_id))
    db.delete(inst)
    db.commit()


# Re-export for main.py compatibility
require_admin = require_manage
ADMIN_ROLES = MANAGE_ROLES
TEACHER_ROLES = STAFF_ROLES
