from datetime import datetime, timezone

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.models import Institute, InstituteInvitation, InstituteMember
from app.roles import ALL_ASSIGNABLE_ROLES


def _normalize_email(email: str) -> str:
    return email.strip().lower()


def create_invitation(
    db: Session,
    institute_id: str,
    role: str,
    invited_by: str,
    *,
    email: str | None = None,
    user_id: str | None = None,
) -> InstituteInvitation:
    if role not in ALL_ASSIGNABLE_ROLES:
        raise ValueError("Invalid role for invitation")

    normalized_email = _normalize_email(email) if email else ""
    if not normalized_email and not user_id:
        raise ValueError("Email or user ID is required")

    if user_id:
        existing_member = db.scalar(
            select(InstituteMember).where(
                InstituteMember.institute_id == institute_id,
                InstituteMember.user_id == user_id,
            )
        )
        if existing_member:
            raise ValueError("User is already a member")

    if normalized_email:
        pending = db.scalar(
            select(InstituteInvitation).where(
                InstituteInvitation.institute_id == institute_id,
                func.lower(InstituteInvitation.invitee_email) == normalized_email,
                InstituteInvitation.status == "pending",
            )
        )
        if pending:
            raise ValueError("Invitation already pending for this email")

    if user_id:
        pending_by_id = db.scalar(
            select(InstituteInvitation).where(
                InstituteInvitation.institute_id == institute_id,
                InstituteInvitation.invitee_user_id == user_id,
                InstituteInvitation.status == "pending",
            )
        )
        if pending_by_id:
            raise ValueError("Invitation already pending for this user")

    inv = InstituteInvitation(
        institute_id=institute_id,
        invitee_user_id=user_id,
        invitee_email=normalized_email,
        role=role,
        status="pending",
        invited_by=invited_by,
    )
    db.add(inv)
    db.commit()
    db.refresh(inv)
    return inv


def _invitation_matches_user(inv: InstituteInvitation, user_id: str, email: str) -> bool:
    normalized = _normalize_email(email)
    if inv.invitee_user_id and inv.invitee_user_id == user_id:
        return True
    if inv.invitee_email and _normalize_email(inv.invitee_email) == normalized:
        return True
    return False


def list_institute_invitations(db: Session, institute_id: str) -> list[InstituteInvitation]:
    return list(
        db.scalars(
            select(InstituteInvitation)
            .where(InstituteInvitation.institute_id == institute_id)
            .order_by(InstituteInvitation.created_at.desc())
        )
    )


def list_user_pending_invitations(
    db: Session, user_id: str, email: str
) -> list[tuple[InstituteInvitation, Institute]]:
    normalized = _normalize_email(email)
    filters = [InstituteInvitation.invitee_user_id == user_id]
    if normalized:
        filters.append(func.lower(InstituteInvitation.invitee_email) == normalized)
    rows = db.execute(
        select(InstituteInvitation, Institute)
        .join(Institute, Institute.id == InstituteInvitation.institute_id)
        .where(
            InstituteInvitation.status == "pending",
            or_(*filters),
        )
        .order_by(InstituteInvitation.created_at.desc())
    )
    return [(inv, inst) for inv, inst in rows]


def accept_invitation(
    db: Session, invitation_id: str, user_id: str, email: str
) -> InstituteMember:
    inv = db.get(InstituteInvitation, invitation_id)
    if not inv or inv.status != "pending":
        raise ValueError("Invitation not found")
    if not _invitation_matches_user(inv, user_id, email):
        raise PermissionError("Not your invitation")

    existing = db.scalar(
        select(InstituteMember).where(
            InstituteMember.institute_id == inv.institute_id,
            InstituteMember.user_id == user_id,
        )
    )
    if existing:
        inv.status = "accepted"
        inv.invitee_user_id = user_id
        inv.responded_at = datetime.now(timezone.utc)
        db.commit()
        return existing

    member = InstituteMember(
        institute_id=inv.institute_id,
        user_id=user_id,
        role=inv.role,
    )
    db.add(member)
    inv.status = "accepted"
    inv.invitee_user_id = user_id
    inv.responded_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(member)
    return member


def reject_invitation(db: Session, invitation_id: str, user_id: str, email: str) -> None:
    inv = db.get(InstituteInvitation, invitation_id)
    if not inv or inv.status != "pending":
        raise ValueError("Invitation not found")
    if not _invitation_matches_user(inv, user_id, email):
        raise PermissionError("Not your invitation")
    inv.status = "rejected"
    inv.invitee_user_id = user_id
    inv.responded_at = datetime.now(timezone.utc)
    db.commit()
