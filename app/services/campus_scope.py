from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Branch, Section, SectionMember
from app.roles import MANAGE_ROLES
from app.services.institutes import require_membership


def get_campus_scope(db: Session, institute_id: str, user_id: str) -> dict:
    member = require_membership(db, institute_id, user_id)
    branches = list(
        db.scalars(
            select(Branch).where(Branch.institute_id == institute_id).order_by(Branch.name)
        )
    )
    if member.role in MANAGE_ROLES or member.role == "principal":
        allowed = branches
    else:
        section_ids = list(
            db.scalars(
                select(SectionMember.section_id).where(SectionMember.user_id == user_id)
            )
        )
        branch_ids = {
            sid
            for sid in db.scalars(
                select(Section.branch_id).where(
                    Section.id.in_(section_ids),
                    Section.institute_id == institute_id,
                    Section.branch_id.is_not(None),
                )
            )
        }
        if branch_ids:
            allowed = [b for b in branches if b.id in branch_ids]
        else:
            primary = next((b for b in branches if b.is_primary), branches[0] if branches else None)
            allowed = [primary] if primary else []

    default = next((b for b in allowed if b.is_primary), allowed[0] if allowed else None)
    return {
        "branches": [
            {"id": b.id, "name": b.name, "isPrimary": b.is_primary} for b in allowed
        ],
        "canSwitch": len(allowed) > 1,
        "defaultBranchId": default.id if default else None,
    }
