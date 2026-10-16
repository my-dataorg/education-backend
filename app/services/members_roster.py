import csv
import io

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import (
    Branch,
    Institute,
    InstituteInvitation,
    InstituteJoinRequest,
    InstituteMember,
    Section,
    SectionMember,
    new_join_code,
)
from app.roles import STAFF_ROLES, STUDENT_ROLE
from app.services.institutes import get_institute_summary
from app.services.user_identity import enrich_rows

PAGE_SIZE = 25


def _kind_for_role(role: str) -> str:
    if role == STUDENT_ROLE:
        return "student"
    if role == "parent":
        return "parent"
    return "staff"


def _branch_people(db: Session, institute_id: str, branch_id: str) -> list[dict]:
    summary = get_institute_summary(db, institute_id)
    branch = next((b for b in summary["branches"] if b["id"] == branch_id), None)
    if not branch:
        return []

    people: list[dict] = []
    seen: set[str] = set()
    for row in branch["teachers"]:
        people.append({**row, "kind": "staff"})
        seen.add(row["userId"])
    for row in branch["students"]:
        people.append({**row, "kind": "student"})
        seen.add(row["userId"])

    primary = next((b for b in summary["branches"] if b["isPrimary"]), None)
    if primary and branch_id == primary["id"]:
        assigned = set()
        for b in summary["branches"]:
            for t in b["teachers"]:
                assigned.add(t["userId"])
            for s in b["students"]:
                assigned.add(s["userId"])
        for member in db.scalars(
            select(InstituteMember).where(InstituteMember.institute_id == institute_id)
        ):
            if member.user_id in seen or member.user_id in assigned:
                continue
            kind = _kind_for_role(member.role)
            if kind == "parent":
                people.append({"userId": member.user_id, "role": member.role, "kind": "parent"})
                seen.add(member.user_id)
            elif member.role in STAFF_ROLES:
                people.append({"userId": member.user_id, "role": member.role, "kind": "staff"})
                seen.add(member.user_id)
            elif member.role == STUDENT_ROLE:
                people.append({"userId": member.user_id, "role": member.role, "kind": "student"})
                seen.add(member.user_id)

    section_ids = list(
        db.scalars(select(Section.id).where(Section.branch_id == branch_id)).all()
    )
    class_by_user: dict[str, str] = {}
    for sid in section_ids:
        section = db.get(Section, sid)
        if not section:
            continue
        label = f"{section.class_name} · {section.name}".strip(" ·")
        for sm in db.scalars(select(SectionMember).where(SectionMember.section_id == sid)):
            if sm.member_type == "student" and sm.user_id not in class_by_user:
                class_by_user[sm.user_id] = label

    enriched = enrich_rows(people)
    for row in enriched:
        row["status"] = "active"
        row["classLabel"] = class_by_user.get(row["userId"], "")
        row["admissionNo"] = ""
        row["phone"] = row.get("username") or ""
    return enriched


def _counts(db: Session, institute_id: str, branch_id: str) -> dict[str, int]:
    people = _branch_people(db, institute_id, branch_id)
    staff = sum(1 for p in people if p["kind"] == "staff")
    students = sum(1 for p in people if p["kind"] == "student")
    parents = sum(1 for p in people if p["kind"] == "parent")
    pending_requests = (
        db.scalar(
            select(func.count())
            .select_from(InstituteJoinRequest)
            .where(
                InstituteJoinRequest.institute_id == institute_id,
                InstituteJoinRequest.status == "pending",
            )
        )
        or 0
    )
    pending_invites = (
        db.scalar(
            select(func.count())
            .select_from(InstituteInvitation)
            .where(
                InstituteInvitation.institute_id == institute_id,
                InstituteInvitation.status == "pending",
            )
        )
        or 0
    )
    return {
        "all": staff + students + parents,
        "staff": staff,
        "students": students,
        "parents": parents,
        "requests": pending_requests,
        "invitations": pending_invites,
    }


def list_roster(
    db: Session,
    institute_id: str,
    *,
    branch_id: str,
    tab: str = "all",
    q: str = "",
    page: int = 1,
    member_type: str = "all",
    status: str = "all",
) -> dict:
    people = _branch_people(db, institute_id, branch_id)
    counts = _counts(db, institute_id, branch_id)

    if tab == "staff":
        people = [p for p in people if p["kind"] == "staff"]
    elif tab == "students":
        people = [p for p in people if p["kind"] == "student"]
    elif tab == "parents":
        people = [p for p in people if p["kind"] == "parent"]

    if member_type != "all":
        people = [p for p in people if p["kind"] == member_type]

    if status != "all":
        people = [p for p in people if p.get("status") == status]

    query = q.strip().lower()
    if query:
        people = [
            p
            for p in people
            if query
            in " ".join(
                str(p.get(key, "") or "")
                for key in (
                    "displayName",
                    "firstName",
                    "lastName",
                    "username",
                    "email",
                    "admissionNo",
                    "phone",
                    "classLabel",
                )
            ).lower()
        ]

    total = len(people)
    page = max(1, page)
    start = (page - 1) * PAGE_SIZE
    items = people[start : start + PAGE_SIZE]

    return {
        "items": items,
        "page": page,
        "pageSize": PAGE_SIZE,
        "total": total,
        "counts": counts,
    }


def export_roster_csv(
    db: Session,
    institute_id: str,
    *,
    branch_id: str,
    tab: str,
    q: str,
    member_type: str,
    status: str,
) -> str:
    first = list_roster(
        db,
        institute_id,
        branch_id=branch_id,
        tab=tab,
        q=q,
        page=1,
        member_type=member_type,
        status=status,
    )
    items = list(first["items"])
    page = 1
    while page * first["pageSize"] < first["total"]:
        page += 1
        chunk = list_roster(
            db,
            institute_id,
            branch_id=branch_id,
            tab=tab,
            q=q,
            page=page,
            member_type=member_type,
            status=status,
        )
        items.extend(chunk["items"])

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["Name", "Type", "Role", "Class", "Status", "Email", "User ID"])
    for row in items:
        name = row.get("displayName") or f"{row.get('firstName', '')} {row.get('lastName', '')}".strip()
        writer.writerow(
            [
                name,
                row.get("kind", ""),
                row.get("role", ""),
                row.get("classLabel", ""),
                row.get("status", ""),
                row.get("email", ""),
                row.get("userId", ""),
            ]
        )
    return buffer.getvalue()


def _primary_branch_id(db: Session, institute_id: str) -> str | None:
    branch = db.scalar(
        select(Branch).where(Branch.institute_id == institute_id, Branch.is_primary.is_(True))
    )
    if branch:
        return branch.id
    return db.scalar(select(Branch.id).where(Branch.institute_id == institute_id).limit(1))


def _join_request_items(db: Session, institute_id: str, q: str | None) -> list[dict]:
    requests = list(
        db.scalars(
            select(InstituteJoinRequest)
            .where(
                InstituteJoinRequest.institute_id == institute_id,
                InstituteJoinRequest.status == "pending",
            )
            .order_by(InstituteJoinRequest.created_at.desc())
        )
    )
    rows = [
        {
            "id": req.id,
            "userId": req.user_id,
            "role": req.requested_role,
            "memberType": "request",
            "kind": "request",
            "status": "pending",
            "message": req.message or "",
        }
        for req in requests
    ]
    rows = enrich_rows(rows)
    if q and len(q.strip()) >= 2:
        needle = q.strip().lower()
        rows = [
            row
            for row in rows
            if needle in (row.get("displayName") or "").lower()
            or needle in (row.get("email") or "").lower()
            or needle in (row.get("userId") or "").lower()
        ]
    return rows


def _invitation_items(db: Session, institute_id: str, q: str | None) -> list[dict]:
    invitations = list(
        db.scalars(
            select(InstituteInvitation)
            .where(InstituteInvitation.institute_id == institute_id)
            .order_by(InstituteInvitation.created_at.desc())
        )
    )
    rows = [
        {
            "id": inv.id,
            "userId": inv.invitee_user_id,
            "role": inv.role,
            "memberType": "invitation",
            "kind": "invitation",
            "status": "invited" if inv.status == "pending" else inv.status,
            "email": inv.invitee_email or "",
        }
        for inv in invitations
    ]
    if q and len(q.strip()) >= 2:
        needle = q.strip().lower()
        rows = [row for row in rows if needle in (row.get("email") or "").lower()]
    return rows


def _tab_counts(db: Session, institute_id: str, campus_id: str | None) -> dict[str, int]:
    branch_id = campus_id or _primary_branch_id(db, institute_id)
    if branch_id:
        return _counts(db, institute_id, branch_id)
    members = list(db.scalars(select(InstituteMember).where(InstituteMember.institute_id == institute_id)))
    pending_requests = (
        db.scalar(
            select(func.count())
            .select_from(InstituteJoinRequest)
            .where(
                InstituteJoinRequest.institute_id == institute_id,
                InstituteJoinRequest.status == "pending",
            )
        )
        or 0
    )
    pending_invites = (
        db.scalar(
            select(func.count())
            .select_from(InstituteInvitation)
            .where(
                InstituteInvitation.institute_id == institute_id,
                InstituteInvitation.status == "pending",
            )
        )
        or 0
    )
    return {
        "all": len(members),
        "staff": sum(1 for m in members if m.role in STAFF_ROLES),
        "students": sum(1 for m in members if m.role == STUDENT_ROLE),
        "parents": sum(1 for m in members if m.role == "parent"),
        "requests": pending_requests,
        "invitations": pending_invites,
    }


def list_members_roster(
    db: Session,
    institute_id: str,
    *,
    tab: str | None = None,
    q: str | None = None,
    page: int = 1,
    page_size: int = PAGE_SIZE,
    role: str | None = None,
    status: str | None = None,
    class_name: str | None = None,
    section_name: str | None = None,
    campus_id: str | None = None,
) -> dict:
    tab_key = (tab or "all").strip().lower()
    if tab_key in ("invites",):
        tab_key = "invitations"
    tab_counts = _tab_counts(db, institute_id, campus_id)

    if tab_key == "requests":
        items = _join_request_items(db, institute_id, q)
    elif tab_key == "invitations":
        items = _invitation_items(db, institute_id, q)
    else:
        branch_id = campus_id or _primary_branch_id(db, institute_id)
        if not branch_id:
            raise ValueError("No campus configured for this institute")
        data = list_roster(
            db,
            institute_id,
            branch_id=branch_id,
            tab=tab_key,
            q=q or "",
            page=1,
            member_type="all",
            status=status or "all",
        )
        items = data["items"]
        if role:
            items = [row for row in items if row.get("role") == role]
        if class_name:
            items = [row for row in items if class_name in (row.get("classLabel") or "")]
        if section_name:
            items = [
                row
                for row in items
                if section_name in (row.get("classLabel") or "").split("·")[-1].strip()
            ]
        for row in items:
            row["id"] = row.get("userId") or ""
            row["memberType"] = row.get("kind") or row.get("memberType")
            row["kind"] = row["memberType"]
            parts = (row.get("classLabel") or "").split("·")
            if parts:
                row["className"] = parts[0].strip() if parts else None
                row["sectionName"] = parts[-1].strip() if len(parts) > 1 else None

    total = len(items)
    page = max(1, page)
    page_size = min(max(page_size, 1), 100)
    start = (page - 1) * page_size
    return {
        "items": items[start : start + page_size],
        "total": total,
        "tabCounts": tab_counts,
    }


def export_members_csv(
    db: Session,
    institute_id: str,
    *,
    tab: str | None = None,
    q: str | None = None,
    role: str | None = None,
    status: str | None = None,
    class_name: str | None = None,
    section_name: str | None = None,
    campus_id: str | None = None,
) -> str:
    branch_id = campus_id or _primary_branch_id(db, institute_id)
    if branch_id and tab not in ("requests", "invitations"):
        return export_roster_csv(
            db,
            institute_id,
            branch_id=branch_id,
            tab=tab or "all",
            q=q or "",
            member_type="all",
            status=status or "all",
        )
    data = list_members_roster(
        db,
        institute_id,
        tab=tab,
        q=q,
        page=1,
        page_size=5000,
        role=role,
        status=status,
        class_name=class_name,
        section_name=section_name,
        campus_id=campus_id,
    )
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["userId", "displayName", "email", "role", "memberType", "status"])
    for row in data["items"]:
        writer.writerow(
            [
                row.get("userId") or row.get("id") or "",
                row.get("displayName") or "",
                row.get("email") or "",
                row.get("role") or "",
                row.get("memberType") or row.get("kind") or "",
                row.get("status") or "",
            ]
        )
    return buffer.getvalue()


def regenerate_institute_join_code(db: Session, institute_id: str) -> Institute:
    inst = db.get(Institute, institute_id)
    if not inst:
        raise ValueError("Institute not found")
    inst.join_code = new_join_code()
    db.commit()
    db.refresh(inst)
    return inst
