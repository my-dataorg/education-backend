import json
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    InstituteMember,
    LeaveRequest,
    LeaveRequestApproval,
    PublishedTimetableEntry,
    ScheduleSettings,
    Section,
    Subject,
    TeacherAbsence,
    TeacherSubjectAssignment,
    TimetableSubstitution,
)
from app.roles import MANAGE_ROLES, TEACHING_STAFF_ROLES
from app.schemas import LeaveRequestCreate, TeacherAbsenceCreate
from app.services.attendance_registers import subject_eligible_for_attendance
from app.services.institutes import get_membership
from app.services.sections import require_section_student
from app.services.teacher_coverage import save_absence
from app.services.user_identity import identity_for_user

INSTITUTE_SLOT_ID = "institute"
MANAGER_ROLES = MANAGE_ROLES | {"principal"}


def _parse_attachments(raw: str) -> list[dict]:
    try:
        data = json.loads(raw or "[]")
        return data if isinstance(data, list) else []
    except json.JSONDecodeError:
        return []


def _iso_dt(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _display_name(user_id: str) -> str | None:
    b = identity_for_user(user_id)
    name = (b.get("displayName") or "").strip()
    if name:
        return name
    combined = f"{b.get('firstName', '')} {b.get('lastName', '')}".strip()
    return combined or None


def _approval_out(line: LeaveRequestApproval, subject_name: str | None = None) -> dict:
    return {
        "id": line.id,
        "leaveRequestId": line.leave_request_id,
        "approvalDate": line.approval_date.isoformat(),
        "sectionId": line.section_id,
        "subjectId": line.subject_id,
        "subjectName": subject_name,
        "slotId": line.slot_id,
        "assigneeUserId": line.assignee_user_id,
        "assigneeKind": line.assignee_kind,
        "status": line.status,
        "decidedByUserId": line.decided_by_user_id,
        "decidedAt": _iso_dt(line.decided_at),
        "decisionNote": line.decision_note or "",
    }


def _request_out(db: Session, req: LeaveRequest, *, include_approvals: bool = True) -> dict:
    subject_names: dict[str, str] = {}
    approvals: list[dict] = []
    if include_approvals:
        lines = list(
            db.scalars(
                select(LeaveRequestApproval)
                .where(LeaveRequestApproval.leave_request_id == req.id)
                .order_by(LeaveRequestApproval.approval_date, LeaveRequestApproval.slot_id)
            )
        )
        for line in lines:
            if line.subject_id and line.subject_id not in subject_names:
                subj = db.get(Subject, line.subject_id)
                subject_names[line.subject_id] = subj.name if subj else ""
            approvals.append(_approval_out(line, subject_names.get(line.subject_id or "")))
    out = {
        "id": req.id,
        "instituteId": req.institute_id,
        "requesterUserId": req.requester_user_id,
        "requesterRole": req.requester_role,
        "sectionId": req.section_id,
        "startDate": req.start_date.isoformat(),
        "endDate": req.end_date.isoformat(),
        "purpose": req.purpose or "",
        "body": req.body or "",
        "attachments": _parse_attachments(req.attachments_json),
        "status": req.status,
        "createdAt": _iso_dt(req.created_at),
        "approvals": approvals,
    }
    out["requesterName"] = _display_name(req.requester_user_id)
    for a in approvals:
        a["assigneeName"] = _display_name(a["assigneeUserId"])
    return out


def _manager_user_ids(db: Session, institute_id: str, exclude_user_id: str) -> list[str]:
    rows = list(
        db.scalars(
            select(InstituteMember).where(
                InstituteMember.institute_id == institute_id,
                InstituteMember.role.in_(tuple(MANAGER_ROLES)),
            )
        )
    )
    order = {"owner": 0, "principal": 1, "admin": 2}
    ids = []
    for row in sorted(rows, key=lambda r: order.get(r.role, 9)):
        if row.user_id != exclude_user_id:
            ids.append(row.user_id)
    return ids


def _require_published_timetable(db: Session, institute_id: str) -> None:
    settings = db.get(ScheduleSettings, institute_id)
    if not settings or not settings.published_at:
        raise ValueError("Timetable not published")


def _period_teacher(
    db: Session,
    section_id: str,
    subject_id: str,
    teacher_id: str | None,
) -> str | None:
    if teacher_id:
        return teacher_id
    return db.scalar(
        select(TeacherSubjectAssignment.teacher_id).where(
            TeacherSubjectAssignment.section_id == section_id,
            TeacherSubjectAssignment.subject_id == subject_id,
        )
    )


def _assignee_for_period(
    db: Session,
    institute_id: str,
    section_id: str,
    slot_id: str,
    on_date: date,
    teacher_id: str | None,
) -> tuple[str | None, str]:
    if not teacher_id:
        return None, "subject_teacher"
    sub_row = db.scalar(
        select(TimetableSubstitution).where(
            TimetableSubstitution.institute_id == institute_id,
            TimetableSubstitution.substitution_date == on_date,
            TimetableSubstitution.slot_id == slot_id,
            TimetableSubstitution.section_id == section_id,
        )
    )
    if sub_row:
        return sub_row.substitute_teacher_id, "substitute"
    absence = db.scalar(
        select(TeacherAbsence).where(
            TeacherAbsence.institute_id == institute_id,
            TeacherAbsence.teacher_id == teacher_id,
            TeacherAbsence.absence_date == on_date,
        )
    )
    if absence and absence.substitute_teacher_id:
        return absence.substitute_teacher_id, "substitute"
    return teacher_id, "subject_teacher"


def _build_student_approval_lines(
    db: Session,
    institute_id: str,
    section_id: str,
    start: date,
    end: date,
) -> list[dict[str, Any]]:
    _require_published_timetable(db, institute_id)
    lines: list[dict[str, Any]] = []
    cur = start
    while cur <= end:
        dow = cur.isoweekday()
        entries = list(
            db.scalars(
                select(PublishedTimetableEntry).where(
                    PublishedTimetableEntry.section_id == section_id,
                    PublishedTimetableEntry.day_of_week == dow,
                )
            )
        )
        for entry in entries:
            subject = db.get(Subject, entry.subject_id)
            if not subject_eligible_for_attendance(subject):
                continue
            teacher_id = _period_teacher(db, section_id, entry.subject_id, entry.teacher_id)
            assignee, kind = _assignee_for_period(
                db, institute_id, section_id, entry.slot_id, cur, teacher_id
            )
            if not assignee:
                continue
            lines.append(
                {
                    "approval_date": cur,
                    "section_id": section_id,
                    "subject_id": entry.subject_id,
                    "slot_id": entry.slot_id,
                    "assignee_user_id": assignee,
                    "assignee_kind": kind,
                }
            )
        cur += timedelta(days=1)
    if not lines:
        raise ValueError("No teaching periods found on leave dates (check published timetable)")
    return lines


def _build_institute_manager_line(
    db: Session,
    institute_id: str,
    requester_user_id: str,
    start: date,
) -> dict[str, Any]:
    managers = _manager_user_ids(db, institute_id, requester_user_id)
    if not managers:
        raise ValueError("No institute manager available to approve this leave")
    return {
        "approval_date": start,
        "section_id": None,
        "subject_id": None,
        "slot_id": INSTITUTE_SLOT_ID,
        "assignee_user_id": managers[0],
        "assignee_kind": "institute_manager",
    }


def _student_leave_shape(req: LeaveRequest) -> dict:
    reason = req.purpose.strip()
    if req.body.strip():
        reason = f"{reason}\n{req.body}".strip() if reason else req.body.strip()
    return {
        "id": req.id,
        "studentId": req.requester_user_id,
        "startDate": req.start_date.isoformat(),
        "endDate": req.end_date.isoformat(),
        "reason": reason or req.purpose or "",
        "status": req.status,
        "createdAt": _iso_dt(req.created_at),
    }


def create_leave_request(
    db: Session,
    institute_id: str,
    user_id: str,
    body: LeaveRequestCreate,
) -> dict:
    member = get_membership(db, institute_id, user_id)
    if not member:
        raise PermissionError("Not a member of this institute")
    if body.endDate < body.startDate:
        raise ValueError("End date must be on or after start date")

    role = member.role
    section_id = body.sectionId
    if role == "student":
        if not section_id:
            raise ValueError("sectionId is required for student leave")
        require_section_student(db, section_id, user_id)
        line_specs = _build_student_approval_lines(db, institute_id, section_id, body.startDate, body.endDate)
    elif role in TEACHING_STAFF_ROLES or role in MANAGER_ROLES:
        section_id = None
        line_specs = [_build_institute_manager_line(db, institute_id, user_id, body.startDate)]
    else:
        raise PermissionError("Your role cannot submit leave requests")

    attachments = [a.model_dump() for a in body.attachments]
    req = LeaveRequest(
        id=str(uuid.uuid4()),
        institute_id=institute_id,
        requester_user_id=user_id,
        requester_role=role,
        section_id=section_id,
        start_date=body.startDate,
        end_date=body.endDate,
        purpose=body.purpose.strip(),
        body=body.body.strip(),
        attachments_json=json.dumps(attachments),
        status="pending",
    )
    db.add(req)
    for spec in line_specs:
        db.add(
            LeaveRequestApproval(
                id=str(uuid.uuid4()),
                leave_request_id=req.id,
                approval_date=spec["approval_date"],
                section_id=spec["section_id"],
                subject_id=spec["subject_id"],
                slot_id=spec["slot_id"],
                assignee_user_id=spec["assignee_user_id"],
                assignee_kind=spec["assignee_kind"],
                status="pending",
            )
        )
    db.commit()
    db.refresh(req)
    return _request_out(db, req)


def list_my_leave_requests(db: Session, institute_id: str, user_id: str) -> list[dict]:
    if not get_membership(db, institute_id, user_id):
        raise PermissionError("Not a member of this institute")
    rows = list(
        db.scalars(
            select(LeaveRequest)
            .where(
                LeaveRequest.institute_id == institute_id,
                LeaveRequest.requester_user_id == user_id,
            )
            .order_by(LeaveRequest.created_at.desc())
        )
    )
    return [_request_out(db, r) for r in rows]


def list_inbox(db: Session, institute_id: str, user_id: str) -> list[dict]:
    if not get_membership(db, institute_id, user_id):
        raise PermissionError("Not a member of this institute")
    lines = list(
        db.scalars(
            select(LeaveRequestApproval)
            .join(LeaveRequest, LeaveRequest.id == LeaveRequestApproval.leave_request_id)
            .where(
                LeaveRequest.institute_id == institute_id,
                LeaveRequestApproval.status == "pending",
                LeaveRequest.status == "pending",
            )
            .order_by(LeaveRequestApproval.approval_date)
        )
    )
    out: list[dict] = []
    for line in lines:
        if not _can_decide_line(db, institute_id, user_id, line):
            continue
        req = db.get(LeaveRequest, line.leave_request_id)
        if not req:
            continue
        subject_name = None
        if line.subject_id:
            subj = db.get(Subject, line.subject_id)
            subject_name = subj.name if subj else None
        row = _approval_out(line, subject_name)
        row["request"] = _request_out(db, req, include_approvals=False)
        out.append(row)
    return out


def list_institute_leave_requests(
    db: Session,
    institute_id: str,
    user_id: str,
    *,
    status: str | None = None,
) -> list[dict]:
    member = get_membership(db, institute_id, user_id)
    if not member or member.role not in MANAGER_ROLES:
        raise PermissionError("Institute managers only")
    stmt = select(LeaveRequest).where(LeaveRequest.institute_id == institute_id)
    if status:
        stmt = stmt.where(LeaveRequest.status == status)
    rows = list(db.scalars(stmt.order_by(LeaveRequest.created_at.desc())))
    return [_request_out(db, r) for r in rows]


def _can_decide_line(
    db: Session,
    institute_id: str,
    user_id: str,
    line: LeaveRequestApproval,
) -> bool:
    if line.status != "pending":
        return False
    req = db.get(LeaveRequest, line.leave_request_id)
    if not req or req.requester_user_id == user_id:
        return False
    if line.assignee_kind == "institute_manager":
        return user_id in _manager_user_ids(db, institute_id, req.requester_user_id)
    return line.assignee_user_id == user_id


def _recompute_request_status(db: Session, req: LeaveRequest) -> None:
    lines = list(
        db.scalars(select(LeaveRequestApproval).where(LeaveRequestApproval.leave_request_id == req.id))
    )
    if any(l.status == "rejected" for l in lines):
        req.status = "rejected"
    elif lines and all(l.status == "approved" for l in lines):
        req.status = "approved"
    else:
        req.status = "pending"


def _sync_staff_absences(db: Session, req: LeaveRequest) -> None:
    if req.requester_role not in TEACHING_STAFF_ROLES:
        return
    cur = req.start_date
    note = f"Leave request {req.id}"
    while cur <= req.end_date:
        save_absence(
            db,
            req.institute_id,
            TeacherAbsenceCreate(
                teacherId=req.requester_user_id,
                absenceDate=cur,
                substituteTeacherId=None,
                note=note,
            ),
        )
        cur += timedelta(days=1)


def decide_approval_line(
    db: Session,
    institute_id: str,
    request_id: str,
    line_id: str,
    user_id: str,
    *,
    approve: bool,
    note: str = "",
) -> dict:
    req = db.get(LeaveRequest, request_id)
    if not req or req.institute_id != institute_id:
        raise ValueError("Leave request not found")
    line = db.get(LeaveRequestApproval, line_id)
    if not line or line.leave_request_id != request_id:
        raise ValueError("Approval line not found")
    if not _can_decide_line(db, institute_id, user_id, line):
        raise PermissionError("You cannot decide this approval line")
    line.status = "approved" if approve else "rejected"
    line.decided_by_user_id = user_id
    line.decided_at = datetime.now(timezone.utc)
    line.decision_note = (note or "").strip()
    _recompute_request_status(db, req)
    if req.status == "approved":
        _sync_staff_absences(db, req)
    db.commit()
    db.refresh(req)
    return _request_out(db, req)


def leave_rows_for_student_in_range(
    db: Session,
    section_id: str,
    student_id: str,
    start: date,
    end: date,
) -> list[dict]:
    rows = list(
        db.scalars(
            select(LeaveRequest).where(
                LeaveRequest.section_id == section_id,
                LeaveRequest.requester_user_id == student_id,
                LeaveRequest.start_date <= end,
                LeaveRequest.end_date >= start,
            )
        )
    )
    out = [_student_leave_shape(r) for r in rows]
    for row in out:
        row["studentName"] = _display_name(row["studentId"])
    return out


def list_section_leave_for_teacher(
    db: Session,
    section_id: str,
    user_id: str,
    status: str | None = None,
) -> list[dict]:
    section = db.get(Section, section_id)
    if not section:
        raise ValueError("Section not found")
    stmt = select(LeaveRequest).where(LeaveRequest.section_id == section_id)
    if status:
        stmt = stmt.where(LeaveRequest.status == status)
    rows = list(db.scalars(stmt.order_by(LeaveRequest.created_at.desc())))
    out = [_student_leave_shape(r) for r in rows]
    for row in out:
        row["studentName"] = _display_name(row["studentId"])
    return out


def staff_attendance_summary(
    db: Session,
    institute_id: str,
    user_id: str,
    year: int,
    month: int,
) -> dict:
    if not get_membership(db, institute_id, user_id):
        raise PermissionError("Not a member of this institute")
    month_start = date(year, month, 1)
    if month == 12:
        month_end = date(year, 12, 31)
    else:
        month_end = date(year, month + 1, 1) - timedelta(days=1)
    requests = list_my_leave_requests(db, institute_id, user_id)
    status_by_date: dict[str, str] = {}
    for req_dict in requests:
        start = date.fromisoformat(req_dict["startDate"])
        end = date.fromisoformat(req_dict["endDate"])
        cur = max(start, month_start)
        last = min(end, month_end)
        while cur <= last:
            status_by_date[cur.isoformat()] = req_dict["status"]
            cur += timedelta(days=1)
    absences = []
    from app.services.teacher_coverage import list_absences_between  # noqa: PLC0415

    for row in list_absences_between(db, institute_id, month_start, month_end, teacher_id=user_id):
        status_by_date.setdefault(row.absence_date.isoformat(), "absent")
        absences.append(row.absence_date.isoformat())
    return {
        "startDate": month_start.isoformat(),
        "endDate": month_end.isoformat(),
        "statusByDate": status_by_date,
        "requests": [r for r in requests if date.fromisoformat(r["endDate"]) >= month_start and date.fromisoformat(r["startDate"]) <= month_end],
    }
