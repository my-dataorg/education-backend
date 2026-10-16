import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import InstituteCalendarEvent, InstitutePost, SectionMember
from app.roles import MANAGE_ROLES
from app.services.distribution_lists import get_distribution_list
from app.services.institutes import get_membership, require_membership
from app.services.platform_users import get_users_brief

STAFF_ROLES = MANAGE_ROLES | {"principal", "teacher", "lecturer", "professor", "admin"}
TEACHER_ROLES = {"teacher", "lecturer", "professor"}


def parse_id_list(raw: str) -> list[str]:
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, list):
            return [str(x) for x in parsed if x]
    except json.JSONDecodeError:
        pass
    return [part for part in raw.split(",") if part]


def serialize_id_list(ids: list[str]) -> str:
    return json.dumps(ids) if ids else ""


def _user_gender(user_id: str) -> str:
    return (get_users_brief([user_id]).get(user_id, {}).get("gender") or "").lower()


def _student_in_sections(db: Session, user_id: str, section_ids: list[str]) -> bool:
    if not section_ids:
        return False
    return (
        db.scalar(
            select(SectionMember).where(
                SectionMember.user_id == user_id,
                SectionMember.section_id.in_(section_ids),
            )
        )
        is not None
    )


def _matches_gender_filter(user_id: str, role: str, gender_filter: str | None) -> bool:
    if not gender_filter or role != "student":
        return not gender_filter
    gender = _user_gender(user_id)
    if gender_filter == "male":
        return gender == "male"
    if gender_filter == "female":
        return gender == "female"
    return True


def resolve_targeting(
    db: Session,
    institute_id: str,
    audience: str,
    target_section_ids: list[str],
    target_user_ids: list[str],
    student_gender: str | None,
    distribution_list_id: str | None,
) -> tuple[str, list[str], list[str], str | None, str | None]:
    resolved_audience = audience
    resolved_sections = target_section_ids
    resolved_users = target_user_ids
    resolved_gender = student_gender
    resolved_list_id = distribution_list_id

    if distribution_list_id:
        dl = get_distribution_list(db, institute_id, distribution_list_id)
        if not dl:
            raise ValueError("Distribution list not found")
        resolved_audience = dl.audience
        resolved_sections = parse_id_list(dl.target_section_ids)
        resolved_users = parse_id_list(dl.target_user_ids)
        resolved_gender = dl.student_gender
        resolved_list_id = dl.id
    elif resolved_audience == "boys" and not resolved_gender:
        resolved_gender = "male"
    elif resolved_audience == "girls" and not resolved_gender:
        resolved_gender = "female"

    return resolved_audience, resolved_sections, resolved_users, resolved_gender, resolved_list_id


def audience_visible_to_user(
    db: Session,
    user_id: str,
    role: str,
    audience: str,
    section_ids: list[str],
    user_ids: list[str],
    gender_filter: str | None,
) -> bool:
    if role in MANAGE_ROLES or role == "principal":
        return True

    if audience == "custom" or user_ids:
        if user_id in user_ids:
            return True
        if audience == "custom":
            return False

    if audience == "everyone":
        return True
    if audience == "staff" and role in STAFF_ROLES:
        return True
    if audience == "teachers" and role in TEACHER_ROLES:
        return True
    if audience == "principals" and role == "principal":
        return True
    if audience == "students" and role == "student":
        return _matches_gender_filter(user_id, role, gender_filter)
    if audience == "boys" and role == "student":
        return _user_gender(user_id) == "male" and (
            not section_ids or _student_in_sections(db, user_id, section_ids)
        )
    if audience == "girls" and role == "student":
        return _user_gender(user_id) == "female" and (
            not section_ids or _student_in_sections(db, user_id, section_ids)
        )
    if audience == "parents" and role == "parent":
        return True
    if audience == "class":
        if role != "student":
            return False
        if not _student_in_sections(db, user_id, section_ids):
            return False
        return _matches_gender_filter(user_id, role, gender_filter)
    return False


def post_visible_to_user(db: Session, post: InstitutePost, user_id: str, role: str) -> bool:
    audience, section_ids, user_ids, gender_filter, _ = resolve_targeting(
        db,
        post.institute_id,
        post.audience or "everyone",
        parse_id_list(post.target_section_ids),
        parse_id_list(post.target_user_ids),
        post.student_gender,
        post.distribution_list_id,
    )
    return audience_visible_to_user(db, user_id, role, audience, section_ids, user_ids, gender_filter)


def event_visible_to_user(db: Session, event: InstituteCalendarEvent, user_id: str, role: str) -> bool:
    audience, section_ids, user_ids, gender_filter, _ = resolve_targeting(
        db,
        event.institute_id,
        event.audience or "everyone",
        parse_id_list(event.target_section_ids),
        parse_id_list(event.target_user_ids),
        event.student_gender,
        event.distribution_list_id,
    )
    return audience_visible_to_user(db, user_id, role, audience, section_ids, user_ids, gender_filter)


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
    target_user_ids: list[str],
    student_gender: str | None,
    distribution_list_id: str | None,
) -> InstitutePost:
    member = require_membership(db, institute_id, user_id)
    if member.role not in MANAGE_ROLES and member.role not in {"principal", *TEACHER_ROLES}:
        raise PermissionError("Not allowed to post notices")
    if member.role in TEACHER_ROLES and audience not in {
        "class",
        "students",
        "boys",
        "girls",
        "custom",
        "distribution_list",
    }:
        raise PermissionError("Teachers may only post to class or student audiences")

    resolved_audience, resolved_sections, resolved_users, resolved_gender, resolved_list_id = (
        resolve_targeting(
            db,
            institute_id,
            audience,
            target_section_ids,
            target_user_ids,
            student_gender,
            distribution_list_id,
        )
    )

    row = InstitutePost(
        institute_id=institute_id,
        title=title,
        body=body,
        posted_by=user_id,
        audience=resolved_audience,
        target_section_ids=serialize_id_list(resolved_sections),
        target_user_ids=serialize_id_list(resolved_users),
        student_gender=resolved_gender,
        distribution_list_id=resolved_list_id,
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
        "targetSectionIds": parse_id_list(post.target_section_ids),
        "targetUserIds": parse_id_list(post.target_user_ids),
        "studentGender": post.student_gender,
        "distributionListId": post.distribution_list_id,
        "createdAt": post.created_at,
    }


def list_calendar_events(
    db: Session, institute_id: str, user_id: str, branch_id: str | None = None
) -> list[InstituteCalendarEvent]:
    member = require_membership(db, institute_id, user_id)
    stmt = select(InstituteCalendarEvent).where(InstituteCalendarEvent.institute_id == institute_id)
    if branch_id:
        stmt = stmt.where(InstituteCalendarEvent.branch_id == branch_id)
    rows = list(db.scalars(stmt.order_by(InstituteCalendarEvent.event_date)))
    return [row for row in rows if event_visible_to_user(db, row, user_id, member.role)]


def create_calendar_event(
    db: Session,
    institute_id: str,
    user_id: str,
    title: str,
    event_date,
    description: str,
    branch_id: str | None,
    audience: str,
    target_section_ids: list[str],
    target_user_ids: list[str],
    student_gender: str | None,
    distribution_list_id: str | None,
) -> InstituteCalendarEvent:
    member = get_membership(db, institute_id, user_id)
    if not member or (member.role not in MANAGE_ROLES and member.role != "principal"):
        raise PermissionError("Owner or principal role required")

    resolved_audience, resolved_sections, resolved_users, resolved_gender, resolved_list_id = (
        resolve_targeting(
            db,
            institute_id,
            audience,
            target_section_ids,
            target_user_ids,
            student_gender,
            distribution_list_id,
        )
    )

    row = InstituteCalendarEvent(
        institute_id=institute_id,
        branch_id=branch_id,
        title=title,
        description=description,
        event_date=event_date,
        audience=resolved_audience,
        target_section_ids=serialize_id_list(resolved_sections),
        target_user_ids=serialize_id_list(resolved_users),
        student_gender=resolved_gender,
        distribution_list_id=resolved_list_id,
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
        "audience": event.audience,
        "targetSectionIds": parse_id_list(event.target_section_ids),
        "targetUserIds": parse_id_list(event.target_user_ids),
        "studentGender": event.student_gender,
        "distributionListId": event.distribution_list_id,
        "createdBy": event.created_by,
        "createdAt": event.created_at,
    }
