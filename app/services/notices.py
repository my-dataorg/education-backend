import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import InstituteCalendarEvent, InstitutePost, SectionMember
from app.roles import MANAGE_ROLES
from app.services.institutes import get_membership, require_membership


def _parse_section_ids(raw: str) -> list[str]:
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, list):
            return [str(x) for x in parsed]
    except json.JSONDecodeError:
        pass
    return [part for part in raw.split(",") if part]


def _serialize_section_ids(section_ids: list[str]) -> str:
    return json.dumps(section_ids) if section_ids else ""


def post_visible_to_user(db: Session, post: InstitutePost, user_id: str, role: str) -> bool:
    audience = post.audience or "everyone"
    if audience == "everyone":
        return True
    if audience == "staff" and role in MANAGE_ROLES | {"principal", "teacher", "lecturer", "professor", "admin"}:
        return True
    if audience == "students" and role == "student":
        return True
    if audience == "parents" and role == "parent":
        return True
    if audience == "class":
        target_ids = _parse_section_ids(post.target_section_ids)
        if not target_ids:
            return False
        enrolled = db.scalar(
            select(SectionMember).where(
                SectionMember.user_id == user_id,
                SectionMember.section_id.in_(target_ids),
            )
        )
        return enrolled is not None
    return role in MANAGE_ROLES or role == "principal"


def list_posts_for_user(db: Session, institute_id: str, user_id: str) -> list[InstitutePost]:
    member = require_membership(db, institute_id, user_id)
    rows = db.scalars(
        select(InstitutePost)
        .where(InstitutePost.institute_id == institute_id)
        .order_by(InstitutePost.created_at.desc())
    )
    return [row for row in rows if post_visible_to_user(db, row, user_id, member.role)]


def create_post(
    db: Session,
    institute_id: str,
    user_id: str,
    title: str,
    body: str,
    audience: str,
    target_section_ids: list[str],
) -> InstitutePost:
    member = require_membership(db, institute_id, user_id)
    if member.role not in MANAGE_ROLES and member.role not in {"principal", "teacher", "lecturer", "professor"}:
        raise PermissionError("Not allowed to post notices")
    if member.role in {"teacher", "lecturer", "professor"} and audience not in {"class", "students"}:
        raise PermissionError("Teachers may only post to their class or students")
    row = InstitutePost(
        institute_id=institute_id,
        title=title,
        body=body,
        posted_by=user_id,
        audience=audience,
        target_section_ids=_serialize_section_ids(target_section_ids),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def post_to_dict(post: InstitutePost) -> dict:
    return {
        "id": post.id,
        "title": post.title,
        "body": post.body,
        "postedBy": post.posted_by,
        "audience": post.audience,
        "targetSectionIds": _parse_section_ids(post.target_section_ids),
        "createdAt": post.created_at,
    }


def list_calendar_events(
    db: Session, institute_id: str, user_id: str, branch_id: str | None = None
) -> list[InstituteCalendarEvent]:
    require_membership(db, institute_id, user_id)
    stmt = select(InstituteCalendarEvent).where(InstituteCalendarEvent.institute_id == institute_id)
    if branch_id:
        stmt = stmt.where(InstituteCalendarEvent.branch_id == branch_id)
    return list(db.scalars(stmt.order_by(InstituteCalendarEvent.event_date)))


def create_calendar_event(
    db: Session,
    institute_id: str,
    user_id: str,
    title: str,
    event_date,
    description: str,
    branch_id: str | None,
) -> InstituteCalendarEvent:
    member = require_membership(db, institute_id, user_id)
    if member.role not in MANAGE_ROLES and member.role != "principal":
        raise PermissionError("Owner or principal role required")
    row = InstituteCalendarEvent(
        institute_id=institute_id,
        branch_id=branch_id,
        title=title,
        description=description,
        event_date=event_date,
        created_by=user_id,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def calendar_event_to_dict(event: InstituteCalendarEvent) -> dict:
    return {
        "id": event.id,
        "title": event.title,
        "description": event.description,
        "eventDate": event.event_date,
        "branchId": event.branch_id,
        "createdBy": event.created_by,
        "createdAt": event.created_at,
    }
