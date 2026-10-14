from datetime import date, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import (
    Assignment,
    AttendanceRecord,
    InstituteJoinRequest,
    InstitutePost,
    Section,
    SectionMember,
    Submission,
)
from app.services.institutes import require_membership


def get_owner_overview(
    db: Session,
    institute_id: str,
    user_id: str,
    campus_id: str | None,
    day: date,
) -> dict:
    member = require_membership(db, institute_id, user_id)
    if member.role not in {"owner", "principal"}:
        raise PermissionError("Owner or principal role required")

    sections_query = select(Section).where(Section.institute_id == institute_id)
    if campus_id:
        sections_query = sections_query.where(Section.branch_id == campus_id)
    sections = sorted(
        db.scalars(sections_query.order_by(Section.class_name, Section.name)),
        key=lambda section: (
            int(section.class_name) if section.class_name.isdigit() else 999,
            section.name,
        ),
    )
    section_ids = [section.id for section in sections]

    members = list(
        db.scalars(
            select(SectionMember).where(SectionMember.section_id.in_(section_ids))
        )
    ) if section_ids else []
    students = {row.user_id for row in members if row.member_type == "student"}
    staff = {row.user_id for row in members if row.member_type == "teacher"}

    attendance = list(
        db.scalars(
            select(AttendanceRecord).where(
                AttendanceRecord.section_id.in_(section_ids),
                AttendanceRecord.attendance_date == day,
            )
        )
    ) if section_ids else []
    attendance_by_section = []
    for section in sections:
        rows = [row for row in attendance if row.section_id == section.id]
        present = sum(row.status in {"present", "late"} for row in rows)
        attendance_by_section.append(
            {
                "sectionId": section.id,
                "label": f"{section.class_name}-{section.name}",
                "marked": bool(rows),
                "present": present,
                "total": len(rows),
                "percent": round(present / len(rows) * 100) if rows else None,
            }
        )

    join_requests = db.scalar(
        select(func.count()).select_from(InstituteJoinRequest).where(
            InstituteJoinRequest.institute_id == institute_id,
            InstituteJoinRequest.status == "pending",
        )
    ) or 0
    pending_sections = sum(not item["marked"] for item in attendance_by_section)
    assignments = list(
        db.scalars(
            select(Assignment).where(
                Assignment.section_id.in_(section_ids),
                Assignment.created_by.is_not(None),
                Assignment.due_date >= day - timedelta(days=30),
            )
        )
    ) if section_ids else []
    assignment_ids = [item.id for item in assignments]
    submissions = db.scalar(
        select(func.count()).select_from(Submission).where(
            Submission.assignment_id.in_(assignment_ids)
        )
    ) if assignment_ids else 0
    expected = sum(
        sum(row.member_type == "student" for row in members if row.section_id == item.section_id)
        for item in assignments
    )

    upcoming = [
        {
            "id": item.id,
            "type": "assignment",
            "title": item.title,
            "date": item.due_date.isoformat(),
            "sectionId": item.section_id,
        }
        for item in sorted(assignments, key=lambda item: item.due_date or day)[:5]
        if item.due_date
    ]
    posts = list(
        db.scalars(
            select(InstitutePost)
            .where(InstitutePost.institute_id == institute_id)
            .order_by(InstitutePost.created_at.desc())
            .limit(3)
        )
    )
    attention = []
    if join_requests:
        attention.append({"kind": "join_requests", "count": join_requests, "label": f"{join_requests} join requests waiting"})
    if pending_sections and datetime.now().hour >= 10:
        attention.append({"kind": "attendance", "count": pending_sections, "label": f"{pending_sections} classes have not marked attendance today"})

    return {
        "stats": {
            "students": len(students),
            "staff": len(staff),
            "attendancePercent": (
                round(sum(item["present"] for item in attendance_by_section) / sum(item["total"] for item in attendance_by_section) * 100)
                if attendance and sum(item["total"] for item in attendance_by_section)
                else None
            ),
            "unmarkedClasses": pending_sections,
            "assignmentCompletionPercent": round(submissions / expected * 100) if expected else None,
            "pendingApprovals": join_requests,
        },
        "attention": attention,
        "attendanceByClass": attendance_by_section,
        "upcoming": upcoming,
        "posts": [
            {"id": post.id, "title": post.title, "body": post.body, "createdAt": post.created_at}
            for post in posts
        ],
    }
