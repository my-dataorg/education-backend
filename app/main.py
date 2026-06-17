from contextlib import asynccontextmanager
from datetime import date

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.auth import get_current_user, require_education_subscription
from app.config import settings
from app.db.migrate import migrate_invitations, migrate_join_requests, run_migrations, seed_default_branches
from app.db.session import SessionLocal, engine, get_db
from app.models import (
    Assignment,
    Base,
    Branch,
    DailyNote,
    Institute,
    InstituteJoinRequest,
    InstituteMember,
    Section,
    SectionMember,
    Submission,
    new_join_code,
)
from app.schemas import (
    AssignMember,
    AssignmentCreate,
    AssignmentOut,
    BranchCreate,
    BranchOut,
    BranchUpdate,
    InstituteCreate,
    InstituteDetailOut,
    InstituteOut,
    InstituteStats,
    InstituteSummaryOut,
    InvitationCreate,
    InvitationOut,
    InvitationRespondOut,
    JoinInstitute,
    JoinRequestCreate,
    JoinRequestOut,
    JoinRequestRespondOut,
    InstituteLookupOut,
    MemberAdd,
    MemberOut,
    MemberProfileOut,
    MemberRoleUpdate,
    NoteCreate,
    NoteOut,
    SectionCreate,
    SectionEnrollmentOut,
    SectionMemberAssign,
    SectionOut,
    SectionOverviewOut,
    SubmissionCreate,
    SubmissionOut,
    UserSearchOut,
)
from app.services.institutes import (
    ADMIN_ROLES,
    TEACHER_ROLES,
    add_member,
    create_branch,
    delete_branch,
    delete_institute,
    get_institute_stats,
    get_institute_summary,
    get_member_profile,
    get_membership,
    list_branches,
    list_members,
    list_user_institutes,
    remove_member,
    require_admin,
    require_directory_view,
    require_manage,
    require_membership,
    update_branch,
)
from app.services.sections import (
    assign_section_member,
    get_section_overview,
    list_member_sections,
    list_my_enrolled_sections,
    remove_section_member,
    require_section_access,
    require_section_student,
    require_section_teacher,
)
from app.services.join_requests import (
    accept_join_request,
    create_join_request,
    list_institute_join_requests,
    list_user_join_requests,
    reject_join_request,
)
from app.services.invitations import (
    accept_invitation,
    create_invitation,
    list_institute_invitations,
    list_user_pending_invitations,
    reject_invitation,
)
from app.services.keycloak_users import search_users
from app.services.user_identity import enrich_rows, identity_for_user

User = dict


@asynccontextmanager
async def lifespan(_: FastAPI):
    Base.metadata.create_all(bind=engine)
    run_migrations(engine)
    migrate_invitations(engine)
    migrate_join_requests(engine)
    with SessionLocal() as db:
        seed_default_branches(db)
    yield


app = FastAPI(title=settings.app_name, version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins.split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _institute_out(inst: Institute, role: str) -> InstituteOut:
    return InstituteOut(id=inst.id, name=inst.name, joinCode=inst.join_code, role=role)


def _section_out(db: Session, section: Section) -> SectionOut:
    branch_name = None
    if section.branch_id:
        branch = db.get(Branch, section.branch_id)
        branch_name = branch.name if branch else None
    return SectionOut(
        id=section.id,
        name=section.name,
        className=section.class_name,
        branchId=section.branch_id,
        branchName=branch_name,
    )


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/v1/institutes", response_model=list[InstituteOut])
def list_institutes(
    db: Session = Depends(get_db),
    user: User = Depends(require_education_subscription),
):
    institutes = list_user_institutes(db, user["id"])
    return [
        _institute_out(i, get_membership(db, i.id, user["id"]).role)  # type: ignore
        for i in institutes
    ]


@app.post("/v1/institutes", response_model=InstituteOut, status_code=201)
def create_institute(
    body: InstituteCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_education_subscription),
):
    inst = Institute(name=body.name, join_code=new_join_code())
    db.add(inst)
    db.flush()
    db.add(InstituteMember(institute_id=inst.id, user_id=user["id"], role="owner"))
    db.add(
        Branch(
            institute_id=inst.id,
            name="Main campus",
            address="",
            city="",
            is_primary=True,
        )
    )
    db.commit()
    db.refresh(inst)
    return _institute_out(inst, "owner")


@app.post("/v1/institutes/join", response_model=InstituteOut)
def join_institute(
    body: JoinInstitute,
    db: Session = Depends(get_db),
    user: User = Depends(require_education_subscription),
):
    inst = db.scalar(select(Institute).where(Institute.join_code == body.joinCode.upper()))
    if not inst:
        raise HTTPException(status_code=404, detail="Invalid join code")
    if get_membership(db, inst.id, user["id"]):
        member = get_membership(db, inst.id, user["id"])
        return _institute_out(inst, member.role)  # type: ignore
    db.add(InstituteMember(institute_id=inst.id, user_id=user["id"], role="student"))
    db.commit()
    return _institute_out(inst, "student")


@app.get("/v1/institutes/lookup", response_model=InstituteLookupOut)
def lookup_institute(
    joinCode: str,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    inst = db.scalar(select(Institute).where(Institute.join_code == joinCode.upper()))
    if not inst:
        raise HTTPException(status_code=404, detail="Invalid join code")
    return InstituteLookupOut(id=inst.id, name=inst.name)


@app.delete("/v1/institutes/{institute_id}", status_code=204)
def remove_institute(
    institute_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_education_subscription),
):
    try:
        delete_institute(db, institute_id, user["id"])
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@app.get("/v1/institutes/{institute_id}", response_model=InstituteDetailOut)
def get_institute(
    institute_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_education_subscription),
):
    try:
        member = require_membership(db, institute_id, user["id"])
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e)) from e
    inst = db.get(Institute, institute_id)
    if not inst:
        raise HTTPException(status_code=404, detail="Institute not found")
    stats = get_institute_stats(db, institute_id)
    return InstituteDetailOut(
        id=inst.id,
        name=inst.name,
        joinCode=inst.join_code,
        role=member.role,
        createdAt=inst.created_at,
        stats=InstituteStats(**stats),
    )


@app.get("/v1/institutes/{institute_id}/summary", response_model=InstituteSummaryOut)
def institute_summary(
    institute_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_education_subscription),
):
    try:
        require_directory_view(db, institute_id, user["id"])
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e)) from e
    data = get_institute_summary(db, institute_id)
    return InstituteSummaryOut(**data)


@app.get("/v1/institutes/{institute_id}/members", response_model=list[MemberOut])
def get_members(
    institute_id: str,
    group: str | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(require_education_subscription),
):
    try:
        require_directory_view(db, institute_id, user["id"])
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e)) from e
    members = list_members(db, institute_id, group)
    rows = [{"userId": m.user_id, "role": m.role} for m in members]
    return [MemberOut(**row) for row in enrich_rows(rows)]


@app.get("/v1/institutes/{institute_id}/members/{member_user_id}/profile", response_model=MemberProfileOut)
def member_profile(
    institute_id: str,
    member_user_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_education_subscription),
):
    try:
        require_directory_view(db, institute_id, user["id"])
        profile = get_member_profile(db, institute_id, member_user_id)
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    return MemberProfileOut(**profile)


@app.post("/v1/institutes/{institute_id}/members", response_model=MemberOut, status_code=201)
def add_institute_member(
    institute_id: str,
    body: MemberAdd,
    db: Session = Depends(get_db),
    user: User = Depends(require_education_subscription),
):
    try:
        require_manage(db, institute_id, user["id"])
        member = add_member(db, institute_id, body.userId, body.role)
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return MemberOut(userId=member.user_id, role=member.role)


@app.delete("/v1/institutes/{institute_id}/members/{member_user_id}", status_code=204)
def remove_institute_member(
    institute_id: str,
    member_user_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_education_subscription),
):
    try:
        require_manage(db, institute_id, user["id"])
        remove_member(db, institute_id, member_user_id)
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


def _invitation_out(inv, institute_name: str | None = None) -> InvitationOut:
    identity = identity_for_user(inv.invitee_user_id) if inv.invitee_user_id else {}
    return InvitationOut(
        id=inv.id,
        instituteId=inv.institute_id,
        instituteName=institute_name,
        inviteeUserId=inv.invitee_user_id,
        inviteeEmail=inv.invitee_email or identity.get("email") or "",
        inviteeFirstName=identity.get("firstName") or "",
        inviteeLastName=identity.get("lastName") or "",
        inviteeDisplayName=identity.get("displayName") or "",
        inviteeUsername=identity.get("username") or "",
        role=inv.role,
        status=inv.status,
        invitedBy=inv.invited_by,
        createdAt=inv.created_at,
    )


@app.get("/v1/institutes/{institute_id}/invitations", response_model=list[InvitationOut])
def list_invitations(
    institute_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_education_subscription),
):
    try:
        require_manage(db, institute_id, user["id"])
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e)) from e
    inst = db.get(Institute, institute_id)
    invitations = list_institute_invitations(db, institute_id)
    return [_invitation_out(i, inst.name if inst else None) for i in invitations]


@app.post("/v1/institutes/{institute_id}/invitations", response_model=InvitationOut, status_code=201)
def send_invitation(
    institute_id: str,
    body: InvitationCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_education_subscription),
):
    try:
        require_manage(db, institute_id, user["id"])
        inv = create_invitation(
            db,
            institute_id,
            body.role,
            user["id"],
            email=body.email,
            user_id=body.userId,
        )
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    inst = db.get(Institute, institute_id)
    return _invitation_out(inv, inst.name if inst else None)


def _join_request_out(
    req,
    institute_name: str | None = None,
    user_email: str | None = None,
) -> JoinRequestOut:
    identity = identity_for_user(req.user_id)
    email = user_email or identity.get("email") or None
    return JoinRequestOut(
        id=req.id,
        instituteId=req.institute_id,
        instituteName=institute_name,
        userId=req.user_id,
        userEmail=email,
        firstName=identity.get("firstName") or "",
        lastName=identity.get("lastName") or "",
        displayName=identity.get("displayName") or "",
        username=identity.get("username") or "",
        requestedRole=req.requested_role,
        message=req.message or "",
        status=req.status,
        createdAt=req.created_at,
    )


@app.post("/v1/institutes/{institute_id}/join-requests", response_model=JoinRequestOut, status_code=201)
def submit_join_request(
    institute_id: str,
    body: JoinRequestCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    try:
        req = create_join_request(
            db,
            institute_id,
            user["id"],
            body.requestedRole,
            body.message,
            email=user["email"] or "",
        )
    except ValueError as e:
        msg = str(e)
        status = 404 if "not found" in msg.lower() else 400
        raise HTTPException(status_code=status, detail=msg) from e
    inst = db.get(Institute, institute_id)
    return _join_request_out(req, inst.name if inst else None, user.get("email"))


@app.get("/v1/institutes/{institute_id}/join-requests", response_model=list[JoinRequestOut])
def get_join_requests(
    institute_id: str,
    status: str = "pending",
    db: Session = Depends(get_db),
    user: User = Depends(require_education_subscription),
):
    try:
        require_manage(db, institute_id, user["id"])
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e)) from e
    requests = list_institute_join_requests(db, institute_id, status=status)
    inst = db.get(Institute, institute_id)
    name = inst.name if inst else None
    return [_join_request_out(r, name, None) for r in requests]


@app.get("/v1/users/me/join-requests", response_model=list[JoinRequestOut])
def my_join_requests(
    status: str | None = "pending",
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    rows = list_user_join_requests(db, user["id"], status=status)
    return [
        _join_request_out(req, inst.name, user.get("email"))
        for req, inst in rows
    ]


@app.get("/v1/institutes/{institute_id}/users/search", response_model=list[UserSearchOut])
async def search_institute_users(
    institute_id: str,
    q: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_education_subscription),
):
    if len(q.strip()) < 2:
        return []
    try:
        require_manage(db, institute_id, user["id"])
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e)) from e
    rows = await search_users(q.strip())
    return [UserSearchOut(**row) for row in rows]


@app.get("/v1/users/me/invitations", response_model=list[InvitationOut])
def my_invitations(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    rows = list_user_pending_invitations(db, user["id"], user["email"] or "")
    return [_invitation_out(inv, inst.name) for inv, inst in rows]


@app.post("/v1/invitations/{invitation_id}/accept", response_model=InvitationRespondOut)
def accept_invite(
    invitation_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    try:
        member = accept_invitation(db, invitation_id, user["id"], user["email"] or "")
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    return InvitationRespondOut(instituteId=member.institute_id, role=member.role)


@app.post("/v1/join-requests/{request_id}/accept", response_model=JoinRequestRespondOut)
def accept_join_request_route(
    request_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_education_subscription),
):
    req = db.get(InstituteJoinRequest, request_id)
    if not req:
        raise HTTPException(status_code=404, detail="Join request not found")
    try:
        require_manage(db, req.institute_id, user["id"])
        member = accept_join_request(db, request_id, user["id"])
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    return JoinRequestRespondOut(instituteId=member.institute_id, role=member.role)


@app.post("/v1/join-requests/{request_id}/reject", status_code=204)
def reject_join_request_route(
    request_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_education_subscription),
):
    req = db.get(InstituteJoinRequest, request_id)
    if not req:
        raise HTTPException(status_code=404, detail="Join request not found")
    try:
        require_manage(db, req.institute_id, user["id"])
        reject_join_request(db, request_id, user["id"])
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@app.post("/v1/invitations/{invitation_id}/reject", status_code=204)
def reject_invite(
    invitation_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    try:
        reject_invitation(db, invitation_id, user["id"], user["email"] or "")
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@app.get("/v1/institutes/{institute_id}/branches", response_model=list[BranchOut])
def get_branches(
    institute_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_education_subscription),
):
    try:
        require_admin(db, institute_id, user["id"])
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e)) from e
    branches = list_branches(db, institute_id)
    return [
        BranchOut(
            id=b.id,
            name=b.name,
            address=b.address,
            city=b.city,
            isPrimary=b.is_primary,
            sectionCount=count,
        )
        for b, count in branches
    ]


@app.post("/v1/institutes/{institute_id}/branches", response_model=BranchOut, status_code=201)
def add_branch(
    institute_id: str,
    body: BranchCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_education_subscription),
):
    try:
        require_admin(db, institute_id, user["id"])
        branch = create_branch(
            db, institute_id, body.name, body.address, body.city, body.isPrimary
        )
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e)) from e
    return BranchOut(
        id=branch.id,
        name=branch.name,
        address=branch.address,
        city=branch.city,
        isPrimary=branch.is_primary,
        sectionCount=0,
    )


@app.patch("/v1/institutes/{institute_id}/branches/{branch_id}", response_model=BranchOut)
def edit_branch(
    institute_id: str,
    branch_id: str,
    body: BranchUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require_education_subscription),
):
    try:
        require_admin(db, institute_id, user["id"])
        branch = update_branch(
            db,
            institute_id,
            branch_id,
            name=body.name,
            address=body.address,
            city=body.city,
            isPrimary=body.isPrimary,
        )
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    count = db.scalar(
        select(func.count()).select_from(Section).where(Section.branch_id == branch_id)
    )
    return BranchOut(
        id=branch.id,
        name=branch.name,
        address=branch.address,
        city=branch.city,
        isPrimary=branch.is_primary,
        sectionCount=count or 0,
    )


@app.delete("/v1/institutes/{institute_id}/branches/{branch_id}", status_code=204)
def remove_branch(
    institute_id: str,
    branch_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_education_subscription),
):
    try:
        require_admin(db, institute_id, user["id"])
        delete_branch(db, institute_id, branch_id)
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@app.patch("/v1/institutes/{institute_id}/members/{member_user_id}")
def update_member_role(
    institute_id: str,
    member_user_id: str,
    body: MemberRoleUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require_education_subscription),
):
    try:
        require_manage(db, institute_id, user["id"])
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e)) from e
    member = get_membership(db, institute_id, member_user_id)
    if not member:
        raise HTTPException(status_code=404, detail="Member not found")
    if member.role == "owner":
        raise HTTPException(status_code=400, detail="Cannot change owner role")
    member.role = body.role
    db.commit()
    return {"userId": member_user_id, "role": member.role}


@app.get("/v1/institutes/{institute_id}/sections", response_model=list[SectionOut])
def list_sections(
    institute_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_education_subscription),
):
    try:
        require_membership(db, institute_id, user["id"])
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e)) from e
    sections = db.scalars(
        select(Section).where(Section.institute_id == institute_id).order_by(Section.name)
    )
    return [_section_out(db, s) for s in sections]


@app.post("/v1/institutes/{institute_id}/sections", response_model=SectionOut, status_code=201)
def create_section(
    institute_id: str,
    body: SectionCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_education_subscription),
):
    try:
        require_admin(db, institute_id, user["id"])
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e)) from e
    if body.branchId:
        branch = db.scalar(
            select(Branch).where(Branch.id == body.branchId, Branch.institute_id == institute_id)
        )
        if not branch:
            raise HTTPException(status_code=400, detail="Invalid branch")
    section = Section(
        institute_id=institute_id,
        name=body.name,
        class_name=body.className,
        branch_id=body.branchId,
    )
    db.add(section)
    db.commit()
    db.refresh(section)
    return _section_out(db, section)


@app.get(
    "/v1/institutes/{institute_id}/members/{member_user_id}/sections",
    response_model=list[SectionEnrollmentOut],
)
def member_sections(
    institute_id: str,
    member_user_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_education_subscription),
):
    try:
        require_manage(db, institute_id, user["id"])
        rows = list_member_sections(db, institute_id, member_user_id)
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    return [
        SectionEnrollmentOut(
            sectionId=r["sectionId"],
            sectionName=r["sectionName"],
            className=r.get("className") or "",
            branchName=r.get("branchName"),
            memberType=r.get("memberType"),
        )
        for r in rows
    ]


@app.get("/v1/users/me/institutes/{institute_id}/sections", response_model=list[SectionOut])
def my_sections(
    institute_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_education_subscription),
):
    try:
        rows = list_my_enrolled_sections(db, institute_id, user["id"])
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e)) from e
    return [
        SectionOut(
            id=r["id"],
            name=r["name"],
            className=r["className"],
            branchId=r.get("branchId"),
            branchName=r.get("branchName"),
        )
        for r in rows
    ]


@app.post("/v1/sections/{section_id}/members")
def assign_section_member_route(
    section_id: str,
    body: SectionMemberAssign,
    db: Session = Depends(get_db),
    user: User = Depends(require_education_subscription),
):
    section = db.get(Section, section_id)
    if not section:
        raise HTTPException(status_code=404, detail="Section not found")
    try:
        require_admin(db, section.institute_id, user["id"])
        row = assign_section_member(db, section_id, body.userId, body.memberType)
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return {"sectionId": section_id, "userId": row.user_id, "memberType": row.member_type}


@app.delete("/v1/sections/{section_id}/members/{member_user_id}", status_code=204)
def unassign_section_member(
    section_id: str,
    member_user_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_education_subscription),
):
    section = db.get(Section, section_id)
    if not section:
        raise HTTPException(status_code=404, detail="Section not found")
    try:
        require_admin(db, section.institute_id, user["id"])
        remove_section_member(db, section_id, member_user_id)
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e)) from e


@app.get("/v1/sections/{section_id}/overview", response_model=SectionOverviewOut)
def section_overview(
    section_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_education_subscription),
):
    try:
        data = get_section_overview(db, section_id, user["id"])
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    return SectionOverviewOut(**data)


@app.post("/v1/sections/{section_id}/teachers")
def assign_teacher(
    section_id: str,
    body: AssignMember,
    db: Session = Depends(get_db),
    user: User = Depends(require_education_subscription),
):
    section = db.get(Section, section_id)
    if not section:
        raise HTTPException(status_code=404, detail="Section not found")
    try:
        require_admin(db, section.institute_id, user["id"])
        assign_section_member(db, section_id, body.userId, "teacher")
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return {"sectionId": section_id, "userId": body.userId, "type": "teacher"}


@app.post("/v1/sections/{section_id}/students")
def assign_student(
    section_id: str,
    body: AssignMember,
    db: Session = Depends(get_db),
    user: User = Depends(require_education_subscription),
):
    section = db.get(Section, section_id)
    if not section:
        raise HTTPException(status_code=404, detail="Section not found")
    try:
        require_admin(db, section.institute_id, user["id"])
        assign_section_member(db, section_id, body.userId, "student")
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return {"sectionId": section_id, "userId": body.userId, "type": "student"}


@app.post("/v1/sections/{section_id}/notes", response_model=NoteOut, status_code=201)
def create_note(
    section_id: str,
    body: NoteCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_education_subscription),
):
    try:
        require_section_teacher(db, section_id, user["id"])
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    note = DailyNote(section_id=section_id, teacher_id=user["id"], content=body.content)
    db.add(note)
    db.commit()
    db.refresh(note)
    return NoteOut(
        id=note.id, content=note.content, noteDate=note.note_date, teacherId=note.teacher_id
    )


@app.get("/v1/sections/{section_id}/notes", response_model=list[NoteOut])
def list_notes(
    section_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_education_subscription),
):
    try:
        require_section_access(db, section_id, user["id"])
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    notes = db.scalars(
        select(DailyNote).where(DailyNote.section_id == section_id).order_by(DailyNote.note_date.desc())
    )
    return [
        NoteOut(id=n.id, content=n.content, noteDate=n.note_date, teacherId=n.teacher_id)
        for n in notes
    ]


@app.post("/v1/sections/{section_id}/assignments", response_model=AssignmentOut, status_code=201)
def create_assignment(
    section_id: str,
    body: AssignmentCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_education_subscription),
):
    try:
        require_section_teacher(db, section_id, user["id"])
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    assignment = Assignment(
        section_id=section_id,
        title=body.title,
        description=body.description,
        due_date=body.dueDate,
        created_by=user["id"],
    )
    db.add(assignment)
    db.commit()
    db.refresh(assignment)
    return AssignmentOut(
        id=assignment.id,
        title=assignment.title,
        description=assignment.description,
        dueDate=assignment.due_date,
    )


@app.get("/v1/sections/{section_id}/assignments", response_model=list[AssignmentOut])
def list_assignments(
    section_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_education_subscription),
):
    try:
        require_section_access(db, section_id, user["id"])
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    items = db.scalars(select(Assignment).where(Assignment.section_id == section_id))
    return [
        AssignmentOut(id=a.id, title=a.title, description=a.description, dueDate=a.due_date)
        for a in items
    ]


@app.post("/v1/assignments/{assignment_id}/submissions", response_model=SubmissionOut, status_code=201)
def submit_assignment(
    assignment_id: str,
    body: SubmissionCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_education_subscription),
):
    assignment = db.get(Assignment, assignment_id)
    if not assignment:
        raise HTTPException(status_code=404, detail="Assignment not found")
    try:
        require_section_student(db, assignment.section_id, user["id"])
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    existing = db.scalar(
        select(Submission).where(
            Submission.assignment_id == assignment_id,
            Submission.student_id == user["id"],
        )
    )
    if existing:
        existing.content = body.content
        db.commit()
        db.refresh(existing)
        sub = existing
    else:
        sub = Submission(assignment_id=assignment_id, student_id=user["id"], content=body.content)
        db.add(sub)
        db.commit()
        db.refresh(sub)
    return SubmissionOut(id=sub.id, content=sub.content, studentId=sub.student_id)
