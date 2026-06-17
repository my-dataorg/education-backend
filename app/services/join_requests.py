from datetime import datetime, timezone
import logging

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models import Institute, InstituteJoinRequest, InstituteMember
from app.platform_client import notify_user
from app.roles import JOIN_REQUEST_ROLES, MANAGE_ROLES, ROLE_LABELS
from app.services.institutes import get_membership
from app.services.membership_hooks import on_member_joined

logger = logging.getLogger(__name__)


def _clear_terminal_requests(
    db: Session, institute_id: str, user_id: str, status: str, keep_id: str
) -> None:
    db.execute(
        delete(InstituteJoinRequest).where(
            InstituteJoinRequest.institute_id == institute_id,
            InstituteJoinRequest.user_id == user_id,
            InstituteJoinRequest.status == status,
            InstituteJoinRequest.id != keep_id,
        )
    )


def create_join_request(
    db: Session,
    institute_id: str,
    user_id: str,
    requested_role: str,
    message: str = "",
    *,
    email: str = "",
) -> InstituteJoinRequest:
    if requested_role not in JOIN_REQUEST_ROLES:
        raise ValueError("Invalid role for join request")

    inst = db.get(Institute, institute_id)
    if not inst:
        raise ValueError("Institute not found")

    if get_membership(db, institute_id, user_id):
        raise ValueError("Already a member of this institute")

    pending = db.scalar(
        select(InstituteJoinRequest).where(
            InstituteJoinRequest.institute_id == institute_id,
            InstituteJoinRequest.user_id == user_id,
            InstituteJoinRequest.status == "pending",
        )
    )
    if pending:
        raise ValueError("Join request already pending")

    req = InstituteJoinRequest(
        institute_id=institute_id,
        user_id=user_id,
        requested_role=requested_role,
        message=message.strip(),
        status="pending",
    )
    db.add(req)
    db.commit()
    db.refresh(req)
    _notify_admins_new_request(db, req, email_hint=email)
    return req


def list_institute_join_requests(
    db: Session, institute_id: str, *, status: str = "pending"
) -> list[InstituteJoinRequest]:
    return list(
        db.scalars(
            select(InstituteJoinRequest)
            .where(
                InstituteJoinRequest.institute_id == institute_id,
                InstituteJoinRequest.status == status,
            )
            .order_by(InstituteJoinRequest.created_at.desc())
        )
    )


def list_user_join_requests(
    db: Session, user_id: str, *, status: str | None = "pending"
) -> list[tuple[InstituteJoinRequest, Institute]]:
    stmt = (
        select(InstituteJoinRequest, Institute)
        .join(Institute, Institute.id == InstituteJoinRequest.institute_id)
        .where(InstituteJoinRequest.user_id == user_id)
        .order_by(InstituteJoinRequest.created_at.desc())
    )
    if status:
        stmt = stmt.where(InstituteJoinRequest.status == status)
    return [(req, inst) for req, inst in db.execute(stmt)]


def accept_join_request(
    db: Session, request_id: str, reviewer_id: str
) -> InstituteMember:
    req = db.get(InstituteJoinRequest, request_id)
    if not req or req.status != "pending":
        raise ValueError("Join request not found")

    existing = get_membership(db, req.institute_id, req.user_id)
    if existing:
        db.delete(req)
        db.commit()
        return existing

    member = InstituteMember(
        institute_id=req.institute_id,
        user_id=req.user_id,
        role=req.requested_role,
    )
    db.add(member)
    _clear_terminal_requests(db, req.institute_id, req.user_id, "accepted", req.id)
    req.status = "accepted"
    req.reviewed_by = reviewer_id
    req.responded_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(member)
    on_member_joined(db, req.institute_id, req.user_id, member.role)
    return member


def reject_join_request(db: Session, request_id: str, reviewer_id: str) -> None:
    req = db.get(InstituteJoinRequest, request_id)
    if not req or req.status != "pending":
        raise ValueError("Join request not found")

    institute = db.get(Institute, req.institute_id)
    institute_name = institute.name if institute else "the institute"
    role_label = ROLE_LABELS.get(req.requested_role, req.requested_role)

    _clear_terminal_requests(db, req.institute_id, req.user_id, "rejected", req.id)
    req.status = "rejected"
    req.reviewed_by = reviewer_id
    req.responded_at = datetime.now(timezone.utc)
    db.commit()

    notify_user(
        req.user_id,
        type="education.join_request.rejected",
        title=f"Join request declined — {institute_name}",
        body=f"Your request to join as {role_label} was not approved.",
        link="http://localhost:3010/institutes",
    )


def _notify_admins_new_request(
    db: Session, req: InstituteJoinRequest, *, email_hint: str
) -> None:
    institute = db.get(Institute, req.institute_id)
    if not institute:
        return
    role_label = ROLE_LABELS.get(req.requested_role, req.requested_role)
    applicant = email_hint or "A user"
    dashboard_link = f"http://localhost:3010/institutes/{req.institute_id}"

    admins = db.scalars(
        select(InstituteMember).where(
            InstituteMember.institute_id == req.institute_id,
            InstituteMember.role.in_(MANAGE_ROLES),
        )
    )
    for admin in admins:
        notify_user(
            admin.user_id,
            type="education.join_request.new",
            title=f"Join request — {institute.name}",
            body=f"{applicant} requested to join as {role_label}.",
            link=dashboard_link,
        )
