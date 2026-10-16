import json
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import GuardianLinkCache, InstituteMember
from app.roles import PARENT_ROLE, STUDENT_ROLE
from app.services.social_client import (
    fetch_guardian_children_from_social,
    read_guardian_cache_stub,
)

CACHE_TTL = timedelta(minutes=10)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def invalidate_guardian_cache(db: Session, guardian_user_id: str) -> None:
    row = db.get(GuardianLinkCache, guardian_user_id)
    if row:
        db.delete(row)
        db.commit()


def get_linked_student_ids(
    db: Session,
    guardian_user_id: str,
    bearer_token: str,
) -> list[str]:
    row = db.get(GuardianLinkCache, guardian_user_id)
    now = _utcnow()
    if row and _as_utc(row.expires_at) > now:
        return json.loads(row.student_ids_json or "[]")

    stub = read_guardian_cache_stub(guardian_user_id)
    student_ids = stub if stub is not None else fetch_guardian_children_from_social(
        guardian_user_id, bearer_token
    )

    expires_at = now + CACHE_TTL
    if row:
        row.student_ids_json = json.dumps(student_ids)
        row.expires_at = expires_at
    else:
        db.add(
            GuardianLinkCache(
                guardian_user_id=guardian_user_id,
                student_ids_json=json.dumps(student_ids),
                expires_at=expires_at,
            )
        )
    db.commit()
    return student_ids


def is_guardian_of_student(
    db: Session,
    guardian_user_id: str,
    student_id: str,
    bearer_token: str,
) -> bool:
    return student_id in get_linked_student_ids(db, guardian_user_id, bearer_token)


def require_parent_membership(db: Session, user_id: str) -> None:
    count = db.scalar(
        select(InstituteMember.id).where(
            InstituteMember.user_id == user_id,
            InstituteMember.role == PARENT_ROLE,
        ).limit(1)
    )
    if not count:
        raise PermissionError("Parent institute membership required")


def student_enrolled_in_institute(db: Session, institute_id: str, student_id: str) -> bool:
    member = db.scalar(
        select(InstituteMember).where(
            InstituteMember.institute_id == institute_id,
            InstituteMember.user_id == student_id,
            InstituteMember.role == STUDENT_ROLE,
        )
    )
    return member is not None


def list_guardian_children(
    db: Session,
    guardian_user_id: str,
    bearer_token: str,
    *,
    institute_id: str | None = None,
) -> list[dict]:
    require_parent_membership(db, guardian_user_id)
    linked = get_linked_student_ids(db, guardian_user_id, bearer_token)
    if not linked:
        return []

    parent_institutes = {
        row.institute_id
        for row in db.scalars(
            select(InstituteMember).where(
                InstituteMember.user_id == guardian_user_id,
                InstituteMember.role == PARENT_ROLE,
            )
        ).all()
    }
    if institute_id:
        if institute_id not in parent_institutes:
            raise PermissionError("Not a parent member of this institute")
        parent_institutes = {institute_id}

    children: list[dict] = []
    for student_id in linked:
        enrollments = db.scalars(
            select(InstituteMember.institute_id).where(
                InstituteMember.user_id == student_id,
                InstituteMember.role == STUDENT_ROLE,
                InstituteMember.institute_id.in_(parent_institutes),
            )
        ).all()
        institute_ids = sorted(set(enrollments))
        if not institute_ids:
            continue
        children.append({"studentId": student_id, "instituteIds": institute_ids})
    return children
