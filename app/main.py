from contextlib import asynccontextmanager
from datetime import date, timedelta

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.responses import Response
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.auth import get_current_user, require_education_subscription
from app.roles import MANAGE_ROLES, STUDENT_ROLE, TIMETABLE_EDIT_ROLES
from app.config import settings
from app.db.migrate import (
    migrate_invitations,
    migrate_activities,
    migrate_institute_rooms,
    migrate_join_requests,
    migrate_schedule,
    migrate_special_days,
    migrate_teacher_absences,
    migrate_teacher_workspace,
    migrate_institute_posts,
    migrate_academic_years,
    migrate_subjects,
    migrate_timetable_publish,
    migrate_institute_role_settings,
    migrate_timetable_substitutions,
    migrate_timetable_school_defaults,
    migrate_mvp_domains,
    migrate_institute_profile,
    migrate_parent_guardian_messaging,
    migrate_section_class_teacher,
    migrate_section_attendance_days,
    migrate_assignment_works,
    migrate_student_leave_requests,
    migrate_section_syllabus,
    run_migrations,
    seed_default_activities,
    seed_default_branches,
)
from app.db.session import SessionLocal, engine, get_db
from app.models import (
    Assignment,
    Activity,
    AttendanceRecord,
    Base,
    Branch,
    DailyNote,
    Institute,
    InstituteJoinRequest,
    InstituteMember,
    Section,
    SectionMember,
    SectionSubject,
    Subject,
    Submission,
    new_join_code,
)
from app.schemas import (
    AssignMember,
    ActivityCreate,
    ActivityOut,
    RoomCreate,
    RoomOut,
    AttendanceOut,
    AttendanceUpdate,
    AssignmentCreate,
    AssignmentOut,
    BranchCreate,
    BranchOut,
    BranchUpdate,
    CampusScopeOut,
    InstituteProfileOut,
    InstituteProfileUpdate,
    InstituteCreate,
    InstituteDetailOut,
    InstituteOut,
    InstituteStats,
    InstituteSummaryOut,
    InstitutePostCreate,
    InstitutePostOut,
    DistributionListCreate,
    DistributionListOut,
    CalendarEventCreate,
    CalendarEventOut,
    ExamCreate,
    ExamUpdate,
    ExamOut,
    MarksUpsert,
    MarkEntryOut,
    FeeStructureCreate,
    FeeStructureOut,
    StudentFeeAssign,
    StudentFeeDueOut,
    PaymentCreate,
    PaymentOut,
    AttendanceSummaryOut,
    AcademicTermOut,
    AcademicYearOut,
    AcademicYearUpdate,
    OwnerOverviewOut,
    InvitationCreate,
    InvitationOut,
    InvitationRespondOut,
    JoinInstitute,
    JoinRequestCreate,
    JoinRequestOut,
    JoinRequestRespondOut,
    InstituteLookupOut,
    MemberAdd,
    MembersRosterOut,
    MemberOut,
    MemberProfileOut,
    MemberRoleUpdate,
    JoinCodeRegenerateOut,
    SubjectTeacherMatrixOut,
    SubjectTeacherPanelOut,
    SubjectTeacherChecksOut,
    SubjectTeacherCopyIn,
    SubjectTeacherCopyOut,
    SubjectTeacherAssignmentsSaveIn,
    NoteCreate,
    NoteOut,
    SectionCreate,
    SectionSubjectAssign,
    SectionSubjectOut,
    SectionSubjectWeeklyPeriodsPatch,
    SyllabusCompletionPatch,
    SyllabusCopyIn,
    SyllabusCopyOut,
    SyllabusWeightsPatch,
    SyllabusNodeCreate,
    SyllabusNodeOut,
    SyllabusNodePatch,
    SyllabusSubjectSummaryOut,
    SyllabusTreeOut,
    InstituteRoleSettingsOut,
    InstituteRoleSettingsUpdate,
    TimetableAutoFillIn,
    TimetableAutoFillOut,
    TimetableSubstitutionsOut,
    TimetableSubstitutionSaveIn,
    SpecialDayListOut,
    SpecialDayIn,
    SectionEnrollmentOut,
    SectionMemberAssign,
    SectionMemberBulkIn,
    SectionMemberBulkOut,
    EnrollmentTransferIn,
    EnrollmentTransferOut,
    SectionOut,
    SectionClassTeacherUpdate,
    SectionOverviewOut,
    SectionClassDashboardOut,
    AttendanceSheetOut,
    StudentLeaveRequestOut,
    AttendancePresentSyncIn,
    ScheduleOut,
    ScheduleUpdate,
    TimetableCellPatch,
    TimetableSchoolCellPatch,
    TimetableApplySchoolDefaultsIn,
    TimetableClashesOut,
    TimetablePeriodLimitWarningsOut,
    TimetableOut,
    TimetablePublishOut,
    TimetableTeacherLoadOut,
    TeacherAbsenceCreate,
    TeacherAbsenceOut,
    SubjectCreate,
    SubjectOut,
    StudentSubjectAssign,
    StudentSubjectOut,
    SubmissionCreate,
    SubmissionOut,
    TeacherSubjectAssign,
    TeacherSubjectOut,
    UserSearchOut,
    GuardianChildrenOut,
    GuardianLinksSeedIn,
    GuardianLinksSeedOut,
    GuardianChildOut,
    ParentThreadCreate,
    ParentThreadOut,
    ParentMessageCreate,
    ParentMessageOut,
    AssignmentWorkCreate,
    AssignmentWorkPatch,
    AssignmentWorkPublishIn,
    AssignmentQuestionsReplaceIn,
    AssignmentResponsesPatchIn,
    AssignmentGradeIn,
)
from app.services.institutes import (
    ADMIN_ROLES,
    TEACHER_ROLES,
    add_member,
    branch_out_dict,
    create_branch,
    delete_branch,
    delete_institute,
    get_institute_stats,
    get_institute_summary,
    institute_profile_dict,
    update_institute_profile,
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
    require_timetable_edit,
    require_timetable_view,
    require_owner,
    update_branch,
)
from app.services.academic_years import get_or_create_active, terms, update_active
from app.services.members_roster import export_members_csv, list_members_roster, regenerate_institute_join_code
from app.services.subject_teachers import (
    apply_subject_teacher_assignments,
    copy_subject_teachers,
    get_subject_teacher_checks,
    get_subject_teacher_matrix,
    list_subject_teacher_panel,
)
from app.services.campus_scope import get_campus_scope
from app.services.overview import get_owner_overview
from app.services.attendance_sheet import get_section_attendance_sheet, save_present_only_attendance
from app.services.student_leave import list_section_leave_requests
from app.services.section_class_dashboard import get_section_class_dashboard
from app.services.section_assignments import (
    create_work,
    get_or_create_attempt,
    get_work,
    grade_attempt,
    list_assigned_student,
    list_questions_teacher,
    list_submissions,
    list_teacher_works,
    patch_work,
    publish_work,
    replace_questions,
    save_responses,
    submit_attempt,
    unpublish_work,
)
from app.services.sections import (
    assign_section_member,
    bulk_assign_section_members,
    delete_section,
    get_section_overview,
    get_student_attendance,
    get_student_insights,
    get_student_performance,
    list_member_sections,
    list_my_enrolled_sections,
    remove_section_member,
    transfer_student_enrollment,
    set_section_class_teacher,
    require_section_access,
    require_section_student,
    require_daily_note_editor,
    require_section_teacher,
    assert_can_mark_attendance,
)
from app.services.schedule import get_schedule, replace_schedule
from app.services.timetable import (
    accept_auto_fill,
    get_timetable,
    list_clashes,
    list_period_limit_warnings,
    list_substitutions,
    patch_cell,
    patch_school_cell,
    apply_school_defaults,
    preview_auto_fill,
    publish_timetable,
    save_substitutions,
    teacher_load,
)
from app.services.special_days import (
    create_special_day,
    delete_special_day,
    list_special_days,
)
from app.services.role_settings import get_role_settings, update_role_settings
from app.services.teacher_coverage import (
    list_absences,
    remove_absence,
    save_absence,
)
from app.services.activities import (
    create_activity,
    delete_activity,
    list_activities,
)
from app.services.rooms import create_room, delete_room, list_rooms
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
from app.services.platform_users import search_users
from app.services.subjects import (
    assign_teacher as assign_subject_teacher,
    assign_student as assign_subject_student,
    create_subject,
    delete_subject,
    link_subject,
    list_section_subjects,
    normalize_teacher_user_ids,
    list_subjects,
    update_section_subject_weekly_periods,
    unlink_subject,
    unassign_teacher,
    unassign_student as unassign_subject_student,
)
from app.services.syllabus import (
    _UNSET,
    apply_weight_updates,
    build_tree,
    copy_syllabus_between_sections,
    create_node,
    delete_node,
    list_syllabus_summaries,
    require_syllabus_admin,
    require_syllabus_completion_editor,
    set_leaf_completion,
    update_node,
)
from app.services.user_identity import enrich_rows, identity_for_user
from app.services import exams as exam_service
from app.services import fees as fee_service
from app.services.attendance_summary import get_attendance_summary
from app.services import distribution_lists as dl_service
from app.services import notices as notice_service
from app.services import reports as report_service
from app.services.guardians import list_guardian_children, set_demo_guardian_links
from app.services import parent_messaging

User = dict


@asynccontextmanager
async def lifespan(_: FastAPI):
    Base.metadata.create_all(bind=engine)
    run_migrations(engine)
    migrate_invitations(engine)
    migrate_join_requests(engine)
    migrate_subjects(engine)
    migrate_activities(engine)
    migrate_institute_rooms(engine)
    migrate_schedule(engine)
    migrate_special_days(engine)
    migrate_teacher_absences(engine)
    migrate_teacher_workspace(engine)
    migrate_institute_posts(engine)
    migrate_academic_years(engine)
    migrate_timetable_publish(engine)
    migrate_institute_role_settings(engine)
    migrate_timetable_substitutions(engine)
    migrate_timetable_school_defaults(engine)
    migrate_mvp_domains(engine)
    migrate_parent_guardian_messaging(engine)
    migrate_institute_profile(engine)
    migrate_section_class_teacher(engine)
    migrate_section_attendance_days(engine)
    migrate_assignment_works(engine)
    migrate_student_leave_requests(engine)
    migrate_section_syllabus(engine)
    with SessionLocal() as db:
        seed_default_branches(db)
        seed_default_activities(db)
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
        classTeacherUserId=section.class_teacher_user_id,
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
    inst = Institute(
        name=body.name,
        join_code=new_join_code(),
        contact_name=body.contactName,
        phone=body.phone,
        address=body.address,
        city=body.city,
        state=body.state,
        postal_code=body.postalCode,
    )
    db.add(inst)
    db.flush()
    db.add(InstituteMember(institute_id=inst.id, user_id=user["id"], role="owner"))
    db.add(
        Branch(
            institute_id=inst.id,
            name="Main campus",
            address=body.address,
            city=body.city,
            state=body.state,
            postal_code=body.postalCode,
            phone=body.phone,
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


def _academic_year_out(db: Session, year) -> AcademicYearOut:
    return AcademicYearOut(
        id=year.id,
        label=year.label,
        startDate=year.start_date,
        endDate=year.end_date,
        board=year.board,
        termCount=year.term_count,
        gradingScale=year.grading_scale,
        medium=year.medium,
        isActive=year.is_active,
        terms=[
            AcademicTermOut(
                id=term.id,
                name=term.name,
                startDate=term.start_date,
                endDate=term.end_date,
                weightPercent=term.weight_percent,
            )
            for term in terms(db, year.id)
        ],
    )


@app.get("/v1/institutes/{institute_id}/academic-year", response_model=AcademicYearOut)
def get_academic_year(
    institute_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_education_subscription),
):
    try:
        return _academic_year_out(db, get_or_create_active(db, institute_id, user["id"]))
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e)) from e


@app.put("/v1/institutes/{institute_id}/academic-year", response_model=AcademicYearOut)
def save_academic_year(
    institute_id: str,
    body: AcademicYearUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require_education_subscription),
):
    try:
        year = update_active(
            db,
            institute_id,
            user["id"],
            {
                "label": body.label,
                "start_date": body.startDate,
                "end_date": body.endDate,
                "board": body.board,
                "term_count": body.termCount,
                "grading_scale": body.gradingScale,
                "medium": body.medium,
            },
        )
        return _academic_year_out(db, year)
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e)) from e


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


@app.get("/v1/institutes/{institute_id}/overview", response_model=OwnerOverviewOut)
def owner_overview(
    institute_id: str,
    campus_id: str | None = None,
    day: date | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(require_education_subscription),
):
    try:
        data = get_owner_overview(
            db,
            institute_id,
            user["id"],
            campus_id,
            day or date.today(),
        )
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e)) from e
    return OwnerOverviewOut(**data)


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


@app.get("/v1/institutes/{institute_id}/members/roster", response_model=MembersRosterOut)
def get_members_roster(
    institute_id: str,
    tab: str | None = None,
    q: str | None = None,
    page: int = 1,
    pageSize: int = 25,
    role: str | None = None,
    status: str | None = None,
    class_name: str | None = Query(None, alias="class"),
    section: str | None = None,
    campus_id: str | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(require_education_subscription),
):
    try:
        require_timetable_view(db, institute_id, user["id"])
        data = list_members_roster(
            db,
            institute_id,
            tab=tab,
            q=q,
            page=page,
            page_size=pageSize,
            role=role,
            status=status,
            class_name=class_name,
            section_name=section,
            campus_id=campus_id,
        )
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return MembersRosterOut(**data)


@app.get("/v1/institutes/{institute_id}/members/export")
def export_members(
    institute_id: str,
    tab: str | None = None,
    q: str | None = None,
    role: str | None = None,
    status: str | None = None,
    class_name: str | None = Query(None, alias="class"),
    section: str | None = None,
    campus_id: str | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(require_education_subscription),
):
    try:
        require_timetable_view(db, institute_id, user["id"])
        csv_body = export_members_csv(
            db,
            institute_id,
            tab=tab,
            q=q,
            role=role,
            status=status,
            class_name=class_name,
            section_name=section,
            campus_id=campus_id,
        )
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e)) from e
    return Response(
        content=csv_body,
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="members.csv"'},
    )


@app.post("/v1/institutes/{institute_id}/join-code/regenerate", response_model=JoinCodeRegenerateOut)
def regenerate_join_code(
    institute_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_education_subscription),
):
    try:
        require_owner(db, institute_id, user["id"])
        inst = regenerate_institute_join_code(db, institute_id)
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    return JoinCodeRegenerateOut(joinCode=inst.join_code)


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
        require_owner(db, institute_id, user["id"])
        inv = create_invitation(
            db,
            institute_id,
            body.role,
            user["id"],
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
def search_institute_users(
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
    rows = search_users(q.strip())
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


@app.get("/v1/institutes/{institute_id}/profile", response_model=InstituteProfileOut)
def get_institute_profile(
    institute_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_education_subscription),
):
    try:
        require_membership(db, institute_id, user["id"])
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e)) from e
    institute = db.get(Institute, institute_id)
    if not institute:
        raise HTTPException(status_code=404, detail="Institute not found")
    return InstituteProfileOut(**institute_profile_dict(institute))


@app.patch("/v1/institutes/{institute_id}/profile", response_model=InstituteProfileOut)
def patch_institute_profile(
    institute_id: str,
    body: InstituteProfileUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require_education_subscription),
):
    try:
        institute = update_institute_profile(
            db,
            institute_id,
            user["id"],
            name=body.name,
            description=body.description,
            email=body.email,
            phone=body.phone,
            website=body.website,
            address=body.address,
            city=body.city,
            state=body.state,
            postalCode=body.postalCode,
        )
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    return InstituteProfileOut(**institute_profile_dict(institute))


@app.get("/v1/institutes/{institute_id}/campus-scope", response_model=CampusScopeOut)
def campus_scope(
    institute_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_education_subscription),
):
    try:
        scope = get_campus_scope(db, institute_id, user["id"])
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e)) from e
    return CampusScopeOut(**scope)


@app.get("/v1/institutes/{institute_id}/branches", response_model=list[BranchOut])
def get_branches(
    institute_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_education_subscription),
):
    try:
        require_membership(db, institute_id, user["id"])
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e)) from e
    branches = list_branches(db, institute_id)
    return [BranchOut(**branch_out_dict(b, count)) for b, count in branches]


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
            db,
            institute_id,
            body.name,
            body.address,
            body.city,
            body.isPrimary,
            state=body.state,
            postal_code=body.postalCode,
            email=body.email,
            phone=body.phone,
        )
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e)) from e
    return BranchOut(**branch_out_dict(branch, 0))


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
            state=body.state,
            postal_code=body.postalCode,
            email=body.email,
            phone=body.phone,
            isPrimary=body.isPrimary,
        )
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    count = db.scalar(
        select(func.count()).select_from(Section).where(Section.branch_id == branch_id)
    )
    return BranchOut(**branch_out_dict(branch, count or 0))


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
        require_directory_view(db, institute_id, user["id"])
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e)) from e
    sections = db.scalars(
        select(Section).where(Section.institute_id == institute_id).order_by(Section.name)
    )
    return [_section_out(db, s) for s in sections]


@app.get("/v1/institutes/{institute_id}/posts", response_model=list[InstitutePostOut])
def list_posts(
    institute_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_education_subscription),
):
    try:
        rows = notice_service.list_posts_for_user(db, institute_id, user["id"])
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e)) from e
    return [InstitutePostOut(**notice_service.post_to_dict(row)) for row in rows]


@app.post("/v1/institutes/{institute_id}/posts", response_model=InstitutePostOut, status_code=201)
def create_post(
    institute_id: str,
    body: InstitutePostCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_education_subscription),
):
    try:
        row = notice_service.create_post(
            db,
            institute_id,
            user["id"],
            body.title,
            body.body,
            body.audience,
            body.targetSectionIds,
            body.targetUserIds,
            body.studentGender,
            body.distributionListId,
        )
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return InstitutePostOut(**notice_service.post_to_dict(row))


@app.get(
    "/v1/institutes/{institute_id}/distribution-lists",
    response_model=list[DistributionListOut],
)
def list_distribution_lists(
    institute_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_education_subscription),
):
    try:
        rows = dl_service.list_distribution_lists(db, institute_id, user["id"])
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e)) from e
    return [DistributionListOut(**dl_service.distribution_list_to_dict(row)) for row in rows]


@app.post(
    "/v1/institutes/{institute_id}/distribution-lists",
    response_model=DistributionListOut,
    status_code=201,
)
def create_distribution_list(
    institute_id: str,
    body: DistributionListCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_education_subscription),
):
    try:
        row = dl_service.create_distribution_list(
            db,
            institute_id,
            user["id"],
            body.name,
            body.audience,
            body.targetSectionIds,
            body.targetUserIds,
            body.studentGender,
        )
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return DistributionListOut(**dl_service.distribution_list_to_dict(row))


@app.delete("/v1/institutes/{institute_id}/distribution-lists/{list_id}", status_code=204)
def delete_distribution_list(
    institute_id: str,
    list_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_education_subscription),
):
    try:
        dl_service.delete_distribution_list(db, institute_id, user["id"], list_id)
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@app.get("/v1/institutes/{institute_id}/schedule", response_model=ScheduleOut)
def read_schedule(
    institute_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_education_subscription),
):
    try:
        require_membership(db, institute_id, user["id"])
        return get_schedule(db, institute_id, user["id"])
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e)) from e


@app.put("/v1/institutes/{institute_id}/schedule", response_model=ScheduleOut)
def update_schedule(
    institute_id: str,
    body: ScheduleUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require_education_subscription),
):
    try:
        require_manage(db, institute_id, user["id"])
        return replace_schedule(db, institute_id, body)
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e)) from e
    except RuntimeError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@app.get(
    "/v1/institutes/{institute_id}/subject-teachers",
    response_model=SubjectTeacherMatrixOut,
)
def read_subject_teacher_matrix(
    institute_id: str,
    show: str = "class",
    campus_id: str | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(require_education_subscription),
):
    try:
        require_timetable_view(db, institute_id, user["id"])
        data = get_subject_teacher_matrix(db, institute_id, campus_id=campus_id, show=show)
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e)) from e
    return SubjectTeacherMatrixOut(**data)


@app.get(
    "/v1/institutes/{institute_id}/subject-teachers/teachers",
    response_model=SubjectTeacherPanelOut,
)
def read_subject_teacher_panel(
    institute_id: str,
    campus_id: str | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(require_education_subscription),
):
    try:
        require_timetable_view(db, institute_id, user["id"])
        data = list_subject_teacher_panel(db, institute_id, campus_id=campus_id)
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e)) from e
    return SubjectTeacherPanelOut(**data)


@app.get(
    "/v1/institutes/{institute_id}/subject-teachers/checks",
    response_model=SubjectTeacherChecksOut,
)
def read_subject_teacher_checks(
    institute_id: str,
    campus_id: str | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(require_education_subscription),
):
    try:
        require_timetable_view(db, institute_id, user["id"])
        data = get_subject_teacher_checks(db, institute_id, campus_id=campus_id)
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e)) from e
    return SubjectTeacherChecksOut(**data)


@app.post(
    "/v1/institutes/{institute_id}/subject-teachers/copy",
    response_model=SubjectTeacherCopyOut,
)
def copy_subject_teacher_assignments(
    institute_id: str,
    body: SubjectTeacherCopyIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_education_subscription),
):
    try:
        require_timetable_edit(db, institute_id, user["id"])
        data = copy_subject_teachers(
            db,
            institute_id,
            source_section_id=body.sourceSectionId,
            target_section_ids=body.targetSectionIds,
            replace_existing=body.replaceExisting,
        )
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return SubjectTeacherCopyOut(**data)


@app.put("/v1/institutes/{institute_id}/subject-teachers/assignments", status_code=204)
def save_subject_teacher_assignments(
    institute_id: str,
    body: SubjectTeacherAssignmentsSaveIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_education_subscription),
):
    try:
        require_timetable_edit(db, institute_id, user["id"])
        apply_subject_teacher_assignments(
            db,
            institute_id,
            [item.model_dump() for item in body.assignments],
        )
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@app.get("/v1/institutes/{institute_id}/timetable", response_model=TimetableOut)
def read_timetable(
    institute_id: str,
    view: str = "class",
    id: str | None = None,
    state: str = "draft",
    db: Session = Depends(get_db),
    user: User = Depends(require_education_subscription),
):
    try:
        from app.roles import TEACHING_STAFF_ROLES
        from app.services.institutes import principal_can_edit_timetable

        member = require_timetable_view(db, institute_id, user["id"])
        can_view_draft = member.role in TIMETABLE_EDIT_ROLES or (
            member.role == "principal" and principal_can_edit_timetable(db, institute_id)
        )
        effective_state = state if can_view_draft else "published"
        effective_view = view if view in {"class", "teacher", "room", "school"} else "class"
        effective_id = id
        if not can_view_draft:
            if not effective_id:
                if member.role in TEACHING_STAFF_ROLES:
                    effective_view = "teacher"
                    effective_id = user["id"]
                elif member.role == STUDENT_ROLE:
                    effective_view = "class"
                    effective_id = db.scalar(
                        select(SectionMember.section_id).where(SectionMember.user_id == user["id"]).limit(1)
                    )
            elif effective_view == "class":
                section_ok = db.scalar(
                    select(Section.id).where(
                        Section.id == effective_id,
                        Section.institute_id == institute_id,
                    )
                )
                if not section_ok:
                    raise HTTPException(status_code=404, detail="Section not found")
            elif effective_view == "teacher":
                teacher_ok = db.scalar(
                    select(InstituteMember.user_id).where(
                        InstituteMember.institute_id == institute_id,
                        InstituteMember.user_id == effective_id,
                        InstituteMember.role.in_(TEACHING_STAFF_ROLES),
                    )
                )
                if not teacher_ok:
                    raise HTTPException(status_code=404, detail="Teacher not found")
        return get_timetable(
            db,
            institute_id,
            view=effective_view,
            item_id=effective_id,
            state=effective_state,
        )
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e)) from e


@app.patch("/v1/institutes/{institute_id}/timetable/cells", response_model=TimetableOut)
def update_timetable_cell(
    institute_id: str,
    body: TimetableCellPatch,
    db: Session = Depends(get_db),
    user: User = Depends(require_education_subscription),
):
    try:
        require_timetable_edit(db, institute_id, user["id"])
        return patch_cell(db, institute_id, body)
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@app.patch("/v1/institutes/{institute_id}/timetable/school-cells", response_model=TimetableOut)
def update_school_timetable_cell(
    institute_id: str,
    body: TimetableSchoolCellPatch,
    db: Session = Depends(get_db),
    user: User = Depends(require_education_subscription),
):
    try:
        require_timetable_edit(db, institute_id, user["id"])
        return patch_school_cell(db, institute_id, body)
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@app.post("/v1/institutes/{institute_id}/timetable/apply-school-defaults")
def apply_school_timetable_defaults(
    institute_id: str,
    body: TimetableApplySchoolDefaultsIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_education_subscription),
):
    try:
        require_timetable_edit(db, institute_id, user["id"])
        return apply_school_defaults(db, institute_id, mode=body.mode)
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@app.get(
    "/v1/institutes/{institute_id}/timetable/clashes",
    response_model=TimetableClashesOut,
)
def read_timetable_clashes(
    institute_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_education_subscription),
):
    try:
        require_timetable_view(db, institute_id, user["id"])
        return list_clashes(db, institute_id)
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e)) from e


@app.get(
    "/v1/institutes/{institute_id}/timetable/period-limit-warnings",
    response_model=TimetablePeriodLimitWarningsOut,
)
def read_timetable_period_limit_warnings(
    institute_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_education_subscription),
):
    try:
        require_timetable_view(db, institute_id, user["id"])
        return list_period_limit_warnings(db, institute_id)
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e)) from e


@app.get(
    "/v1/institutes/{institute_id}/timetable/teacher-load",
    response_model=TimetableTeacherLoadOut,
)
def read_timetable_teacher_load(
    institute_id: str,
    view: str = "class",
    id: str | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(require_education_subscription),
):
    try:
        require_timetable_view(db, institute_id, user["id"])
        if not id:
            raise ValueError("id is required")
        return teacher_load(db, institute_id, view=view, item_id=id)
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@app.post(
    "/v1/institutes/{institute_id}/timetable/publish",
    response_model=TimetablePublishOut,
)
def publish_institute_timetable(
    institute_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_education_subscription),
):
    try:
        require_timetable_edit(db, institute_id, user["id"])
        return publish_timetable(db, institute_id)
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@app.post(
    "/v1/institutes/{institute_id}/timetable/auto-fill",
    response_model=TimetableAutoFillOut,
)
def timetable_auto_fill(
    institute_id: str,
    body: TimetableAutoFillIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_education_subscription),
):
    try:
        require_timetable_edit(db, institute_id, user["id"])
        if body.accept:
            result = accept_auto_fill(
                db,
                institute_id,
                [item.model_dump() for item in body.proposed],
            )
            return TimetableAutoFillOut(appliedCount=result["appliedCount"])
        preview = preview_auto_fill(
            db,
            institute_id,
            section_ids=body.sectionIds or None,
            campus_id=body.campusId,
        )
        return TimetableAutoFillOut(**preview)
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@app.get(
    "/v1/institutes/{institute_id}/timetable/substitutions",
    response_model=TimetableSubstitutionsOut,
)
def read_timetable_substitutions(
    institute_id: str,
    substitution_date: date | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(require_education_subscription),
):
    try:
        require_timetable_view(db, institute_id, user["id"])
        return list_substitutions(db, institute_id, substitution_date or date.today())
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e)) from e


@app.post(
    "/v1/institutes/{institute_id}/timetable/substitutions",
    response_model=TimetableSubstitutionsOut,
)
def write_timetable_substitutions(
    institute_id: str,
    body: TimetableSubstitutionSaveIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_education_subscription),
):
    try:
        require_timetable_edit(db, institute_id, user["id"])
        return save_substitutions(db, institute_id, body.date, body.substitutions)
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@app.get(
    "/v1/institutes/{institute_id}/special-days",
    response_model=SpecialDayListOut,
)
def read_special_days(
    institute_id: str,
    year: str = "current",
    campus_id: str | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(require_education_subscription),
):
    try:
        require_timetable_view(db, institute_id, user["id"])
        return list_special_days(db, institute_id, year=year, campus_id=campus_id)
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e)) from e


@app.post(
    "/v1/institutes/{institute_id}/special-days",
    response_model=SpecialDayListOut,
    status_code=201,
)
def add_special_day(
    institute_id: str,
    body: SpecialDayIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_education_subscription),
):
    try:
        require_timetable_edit(db, institute_id, user["id"])
        item = create_special_day(db, institute_id, body)
        return SpecialDayListOut(items=[item])
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@app.delete("/v1/institutes/{institute_id}/special-days/{special_day_id}", status_code=204)
def remove_special_day(
    institute_id: str,
    special_day_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_education_subscription),
):
    try:
        require_timetable_edit(db, institute_id, user["id"])
        delete_special_day(db, institute_id, special_day_id)
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@app.get(
    "/v1/institutes/{institute_id}/role-settings",
    response_model=InstituteRoleSettingsOut,
)
def read_role_settings(
    institute_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_education_subscription),
):
    try:
        require_membership(db, institute_id, user["id"])
        return get_role_settings(db, institute_id)
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e)) from e


@app.put(
    "/v1/institutes/{institute_id}/role-settings",
    response_model=InstituteRoleSettingsOut,
)
def write_role_settings(
    institute_id: str,
    body: InstituteRoleSettingsUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require_education_subscription),
):
    try:
        return update_role_settings(db, institute_id, user["id"], body)
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e)) from e


@app.get(
    "/v1/institutes/{institute_id}/teacher-absences",
    response_model=list[TeacherAbsenceOut],
)
def get_teacher_absences(
    institute_id: str,
    absence_date: date | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(require_education_subscription),
):
    try:
        require_manage(db, institute_id, user["id"])
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e)) from e
    return [
        TeacherAbsenceOut(
            id=item.id,
            teacherId=item.teacher_id,
            absenceDate=item.absence_date,
            substituteTeacherId=item.substitute_teacher_id,
            note=item.note,
        )
        for item in list_absences(db, institute_id, absence_date or date.today())
    ]


@app.put(
    "/v1/institutes/{institute_id}/teacher-absences",
    response_model=TeacherAbsenceOut,
)
def update_teacher_absence(
    institute_id: str,
    body: TeacherAbsenceCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_education_subscription),
):
    try:
        require_manage(db, institute_id, user["id"])
        item = save_absence(db, institute_id, body)
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return TeacherAbsenceOut(
        id=item.id,
        teacherId=item.teacher_id,
        absenceDate=item.absence_date,
        substituteTeacherId=item.substitute_teacher_id,
        note=item.note,
    )


@app.delete("/v1/institutes/{institute_id}/teacher-absences/{absence_id}", status_code=204)
def delete_teacher_absence(
    institute_id: str,
    absence_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_education_subscription),
):
    try:
        require_manage(db, institute_id, user["id"])
        remove_absence(db, institute_id, absence_id)
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@app.post("/v1/institutes/{institute_id}/sections", response_model=SectionOut, status_code=201)
def create_section(
    institute_id: str,
    body: SectionCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_education_subscription),
):
    try:
        require_owner(db, institute_id, user["id"])
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


@app.patch(
    "/v1/institutes/{institute_id}/sections/{section_id}/class-teacher",
    response_model=SectionOut,
)
def patch_section_class_teacher(
    institute_id: str,
    section_id: str,
    body: SectionClassTeacherUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require_education_subscription),
):
    try:
        member = require_membership(db, institute_id, user["id"])
        if member.role not in TIMETABLE_EDIT_ROLES:
            raise PermissionError("Owner, admin, or principal role required")
        section = set_section_class_teacher(db, institute_id, section_id, body.userId)
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return _section_out(db, section)


@app.delete("/v1/institutes/{institute_id}/sections/{section_id}", status_code=204)
def remove_section(
    institute_id: str,
    section_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_education_subscription),
):
    try:
        require_owner(db, institute_id, user["id"])
        delete_section(db, institute_id, section_id)
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@app.get("/v1/institutes/{institute_id}/subjects", response_model=list[SubjectOut])
def get_subjects(
    institute_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_education_subscription),
):
    try:
        require_membership(db, institute_id, user["id"])
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e)) from e
    return [SubjectOut(id=s.id, name=s.name) for s in list_subjects(db, institute_id)]


@app.post("/v1/institutes/{institute_id}/subjects", response_model=SubjectOut, status_code=201)
def add_subject(
    institute_id: str,
    body: SubjectCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_education_subscription),
):
    try:
        require_owner(db, institute_id, user["id"])
        subject = create_subject(db, institute_id, body.name)
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    return SubjectOut(id=subject.id, name=subject.name)


@app.delete("/v1/institutes/{institute_id}/subjects/{subject_id}", status_code=204)
def remove_subject(
    institute_id: str,
    subject_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_education_subscription),
):
    try:
        require_owner(db, institute_id, user["id"])
        delete_subject(db, institute_id, subject_id)
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@app.get("/v1/institutes/{institute_id}/activities", response_model=list[ActivityOut])
def get_activities(
    institute_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_education_subscription),
):
    try:
        require_membership(db, institute_id, user["id"])
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e)) from e
    return [
        ActivityOut(id=activity.id, name=activity.name)
        for activity in list_activities(db, institute_id)
    ]


@app.post("/v1/institutes/{institute_id}/activities", response_model=ActivityOut, status_code=201)
def add_activity(
    institute_id: str,
    body: ActivityCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_education_subscription),
):
    try:
        require_owner(db, institute_id, user["id"])
        activity = create_activity(db, institute_id, body.name)
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    return ActivityOut(id=activity.id, name=activity.name)


@app.get("/v1/institutes/{institute_id}/rooms", response_model=list[RoomOut])
def get_rooms(
    institute_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_education_subscription),
):
    try:
        require_membership(db, institute_id, user["id"])
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e)) from e
    return [RoomOut(id=room.id, name=room.name) for room in list_rooms(db, institute_id)]


@app.post("/v1/institutes/{institute_id}/rooms", response_model=RoomOut, status_code=201)
def add_room(
    institute_id: str,
    body: RoomCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_education_subscription),
):
    try:
        require_owner(db, institute_id, user["id"])
        room = create_room(db, institute_id, body.name)
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    return RoomOut(id=room.id, name=room.name)


@app.delete("/v1/institutes/{institute_id}/rooms/{room_id}", status_code=204)
def remove_room(
    institute_id: str,
    room_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_education_subscription),
):
    try:
        require_owner(db, institute_id, user["id"])
        delete_room(db, institute_id, room_id)
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e)) from e
    except ValueError as e:
        msg = str(e)
        code = 409 if "used" in msg.lower() else 404
        raise HTTPException(status_code=code, detail=msg) from e


@app.delete("/v1/institutes/{institute_id}/activities/{activity_id}", status_code=204)
def remove_activity(
    institute_id: str,
    activity_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_education_subscription),
):
    try:
        require_owner(db, institute_id, user["id"])
        delete_activity(db, institute_id, activity_id)
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=409 if "used" in str(e) or "Default" in str(e) else 404, detail=str(e)) from e


@app.get("/v1/sections/{section_id}/subjects", response_model=list[SectionSubjectOut])
def get_section_subjects(
    section_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_education_subscription),
):
    section = db.get(Section, section_id)
    if not section:
        raise HTTPException(status_code=404, detail="Section not found")
    try:
        require_section_access(db, section_id, user["id"])
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e)) from e
    return [
        SectionSubjectOut(
            id=row["id"],
            name=row["name"],
            weeklyPeriods=row.get("weeklyPeriods"),
            teachers=[
                TeacherSubjectOut(userId=user_id)
                for user_id in normalize_teacher_user_ids(row.get("teachers") or [])
            ],
            students=[StudentSubjectOut(userId=user_id) for user_id in row.get("students") or []],
        )
        for row in list_section_subjects(db, section_id)
    ]


def _syllabus_can_edit_completion(db: Session, section_id: str, user_id: str) -> bool:
    try:
        require_syllabus_completion_editor(db, section_id, user_id)
        return True
    except (PermissionError, ValueError):
        return False


def _node_to_out(node_dict: dict) -> SyllabusNodeOut:
    return SyllabusNodeOut(
        id=node_dict["id"],
        title=node_dict["title"],
        weightPercent=node_dict["weightPercent"],
        sortOrder=node_dict["sortOrder"],
        completedPercent=node_dict["completedPercent"],
        effectiveCompletedPercent=node_dict["effectiveCompletedPercent"],
        isLeaf=node_dict["isLeaf"],
        canEditCompletion=node_dict["canEditCompletion"],
        children=[_node_to_out(c) for c in node_dict.get("children", [])],
    )


def _find_syllabus_node_dict(nodes: list[dict], node_id: str) -> dict | None:
    for node in nodes:
        if node["id"] == node_id:
            return node
        found = _find_syllabus_node_dict(node.get("children", []), node_id)
        if found:
            return found
    return None


def _tree_to_out(tree: dict) -> SyllabusTreeOut:
    return SyllabusTreeOut(
        subjectId=tree["subjectId"],
        subjectName=tree["subjectName"],
        subjectTotalCompletedPercent=tree["subjectTotalCompletedPercent"],
        nodes=[_node_to_out(n) for n in tree["nodes"]],
    )


@app.post(
    "/v1/institutes/{institute_id}/syllabus/copy",
    response_model=SyllabusCopyOut,
)
def post_copy_section_syllabus(
    institute_id: str,
    body: SyllabusCopyIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_education_subscription),
):
    try:
        require_syllabus_admin(db, institute_id, user["id"])
        data = copy_syllabus_between_sections(
            db,
            institute_id,
            body.sourceSectionId,
            body.targetSectionIds,
        )
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return SyllabusCopyOut(**data)


@app.get("/v1/sections/{section_id}/syllabus", response_model=list[SyllabusSubjectSummaryOut])
def get_section_syllabus_summaries(
    section_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_education_subscription),
):
    section = db.get(Section, section_id)
    if not section:
        raise HTTPException(status_code=404, detail="Section not found")
    try:
        require_section_access(db, section_id, user["id"])
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e)) from e
    return [SyllabusSubjectSummaryOut(**row) for row in list_syllabus_summaries(db, section_id)]


@app.get(
    "/v1/sections/{section_id}/subjects/{subject_id}/syllabus",
    response_model=SyllabusTreeOut,
)
def get_section_subject_syllabus(
    section_id: str,
    subject_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_education_subscription),
):
    section = db.get(Section, section_id)
    if not section:
        raise HTTPException(status_code=404, detail="Section not found")
    try:
        require_section_access(db, section_id, user["id"])
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e)) from e
    try:
        tree = build_tree(
            db,
            section_id,
            subject_id,
            _syllabus_can_edit_completion(db, section_id, user["id"]),
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    return _tree_to_out(tree)


@app.post(
    "/v1/sections/{section_id}/subjects/{subject_id}/syllabus/nodes",
    response_model=SyllabusNodeOut,
    status_code=201,
)
def post_syllabus_node(
    section_id: str,
    subject_id: str,
    body: SyllabusNodeCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_education_subscription),
):
    section = db.get(Section, section_id)
    if not section:
        raise HTTPException(status_code=404, detail="Section not found")
    try:
        require_syllabus_admin(db, section.institute_id, user["id"])
        node = create_node(
            db,
            section_id,
            subject_id,
            body.title,
            body.weightPercent,
            parent_id=body.parentId,
            sort_order=body.sortOrder,
        )
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=400 if "sum" in str(e) else 404, detail=str(e)) from e
    return SyllabusNodeOut(
        id=node.id,
        title=node.title,
        weightPercent=float(node.weight_percent),
        sortOrder=node.sort_order,
        completedPercent=float(node.completed_percent or 0),
        effectiveCompletedPercent=float(node.completed_percent or 0),
        isLeaf=True,
        canEditCompletion=False,
        children=[],
    )


@app.patch(
    "/v1/sections/{section_id}/subjects/{subject_id}/syllabus/nodes/{node_id}",
    response_model=SyllabusNodeOut,
)
def patch_syllabus_node(
    section_id: str,
    subject_id: str,
    node_id: str,
    body: SyllabusNodePatch,
    db: Session = Depends(get_db),
    user: User = Depends(require_education_subscription),
):
    section = db.get(Section, section_id)
    if not section:
        raise HTTPException(status_code=404, detail="Section not found")
    parent_id: str | None | object = (
        body.parentId if "parentId" in body.model_fields_set else _UNSET
    )
    try:
        require_syllabus_admin(db, section.institute_id, user["id"])
        update_node(
            db,
            section_id,
            subject_id,
            node_id,
            title=body.title,
            weight_percent=body.weightPercent,
            parent_id=parent_id,
            sort_order=body.sortOrder,
        )
        tree = build_tree(
            db,
            section_id,
            subject_id,
            _syllabus_can_edit_completion(db, section_id, user["id"]),
        )
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e)) from e
    except ValueError as e:
        detail = str(e)
        status = 400 if "sum" in detail or "weight" in detail.lower() else 404
        raise HTTPException(status_code=status, detail=detail) from e
    node_dict = _find_syllabus_node_dict(tree["nodes"], node_id)
    if not node_dict:
        raise HTTPException(status_code=404, detail="Node not found")
    return _node_to_out(node_dict)


@app.patch(
    "/v1/sections/{section_id}/subjects/{subject_id}/syllabus/weights",
    response_model=SyllabusTreeOut,
)
def patch_syllabus_weights(
    section_id: str,
    subject_id: str,
    body: SyllabusWeightsPatch,
    db: Session = Depends(get_db),
    user: User = Depends(require_education_subscription),
):
    section = db.get(Section, section_id)
    if not section:
        raise HTTPException(status_code=404, detail="Section not found")
    try:
        require_syllabus_admin(db, section.institute_id, user["id"])
        apply_weight_updates(
            db,
            section_id,
            subject_id,
            [(item.nodeId, item.weightPercent) for item in body.weights],
        )
        tree = build_tree(
            db,
            section_id,
            subject_id,
            _syllabus_can_edit_completion(db, section_id, user["id"]),
        )
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e)) from e
    except ValueError as e:
        detail = str(e)
        status = 400 if "sum" in detail or "weight" in detail.lower() else 404
        raise HTTPException(status_code=status, detail=detail) from e
    return _tree_to_out(tree)


@app.delete(
    "/v1/sections/{section_id}/subjects/{subject_id}/syllabus/nodes/{node_id}",
    status_code=204,
)
def delete_syllabus_node(
    section_id: str,
    subject_id: str,
    node_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_education_subscription),
):
    section = db.get(Section, section_id)
    if not section:
        raise HTTPException(status_code=404, detail="Section not found")
    try:
        require_syllabus_admin(db, section.institute_id, user["id"])
        delete_node(db, section_id, subject_id, node_id)
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@app.patch(
    "/v1/sections/{section_id}/subjects/{subject_id}/syllabus/nodes/{node_id}/completion",
    response_model=SyllabusTreeOut,
)
def patch_syllabus_node_completion(
    section_id: str,
    subject_id: str,
    node_id: str,
    body: SyllabusCompletionPatch,
    db: Session = Depends(get_db),
    user: User = Depends(require_education_subscription),
):
    section = db.get(Section, section_id)
    if not section:
        raise HTTPException(status_code=404, detail="Section not found")
    try:
        require_syllabus_completion_editor(db, section_id, user["id"])
        tree = set_leaf_completion(
            db,
            section_id,
            subject_id,
            node_id,
            body.completedPercent,
            user["id"],
        )
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e)) from e
    except ValueError as e:
        detail = str(e)
        status = 422 if "leaf" in detail.lower() else 404
        if "between" in detail:
            status = 400
        raise HTTPException(status_code=status, detail=detail) from e
    return _tree_to_out(tree)


@app.patch(
    "/v1/sections/{section_id}/subjects/{subject_id}",
    response_model=SectionSubjectOut,
)
def patch_section_subject(
    section_id: str,
    subject_id: str,
    body: SectionSubjectWeeklyPeriodsPatch,
    db: Session = Depends(get_db),
    user: User = Depends(require_education_subscription),
):
    try:
        section = db.get(Section, section_id)
        if not section:
            raise ValueError("Section not found")
        require_owner(db, section.institute_id, user["id"])
        update_section_subject_weekly_periods(
            db, section_id, subject_id, body.weeklyPeriods
        )
        subject = db.get(Subject, subject_id)
        if not subject:
            raise ValueError("Subject not found")
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    return SectionSubjectOut(
        id=subject.id,
        name=subject.name,
        weeklyPeriods=body.weeklyPeriods,
    )


@app.post("/v1/sections/{section_id}/subjects", response_model=SectionSubjectOut, status_code=201)
def add_section_subject(
    section_id: str,
    body: SectionSubjectAssign,
    db: Session = Depends(get_db),
    user: User = Depends(require_education_subscription),
):
    try:
        section = db.get(Section, section_id)
        if not section:
            raise ValueError("Section not found")
        require_owner(db, section.institute_id, user["id"])
        subject = link_subject(
            db, section_id, body.subjectId, weekly_periods=body.weeklyPeriods
        )
        link = db.scalar(
            select(SectionSubject).where(
                SectionSubject.section_id == section_id,
                SectionSubject.subject_id == body.subjectId,
            )
        )
        weekly_periods = link.weekly_periods if link else body.weeklyPeriods
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    return SectionSubjectOut(
        id=subject.id, name=subject.name, weeklyPeriods=weekly_periods
    )


@app.delete("/v1/sections/{section_id}/subjects/{subject_id}", status_code=204)
def remove_section_subject(
    section_id: str,
    subject_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_education_subscription),
):
    try:
        section = db.get(Section, section_id)
        if not section:
            raise ValueError("Section not found")
        require_owner(db, section.institute_id, user["id"])
        unlink_subject(db, section_id, subject_id)
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@app.post(
    "/v1/sections/{section_id}/subjects/{subject_id}/teachers",
    response_model=TeacherSubjectOut,
    status_code=201,
)
def add_subject_teacher(
    section_id: str,
    subject_id: str,
    body: TeacherSubjectAssign,
    db: Session = Depends(get_db),
    user: User = Depends(require_education_subscription),
):
    try:
        section = db.get(Section, section_id)
        if not section:
            raise ValueError("Section not found")
        require_owner(db, section.institute_id, user["id"])
        assign_subject_teacher(db, section_id, subject_id, body.userId)
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return TeacherSubjectOut(userId=body.userId)


@app.delete(
    "/v1/sections/{section_id}/subjects/{subject_id}/teachers/{teacher_id}",
    status_code=204,
)
def remove_subject_teacher(
    section_id: str,
    subject_id: str,
    teacher_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_education_subscription),
):
    try:
        section = db.get(Section, section_id)
        if not section:
            raise ValueError("Section not found")
        require_owner(db, section.institute_id, user["id"])
        unassign_teacher(db, section_id, subject_id, teacher_id)
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@app.post(
    "/v1/sections/{section_id}/subjects/{subject_id}/students",
    response_model=StudentSubjectOut,
    status_code=201,
)
def add_subject_student(
    section_id: str,
    subject_id: str,
    body: StudentSubjectAssign,
    db: Session = Depends(get_db),
    user: User = Depends(require_education_subscription),
):
    try:
        section = db.get(Section, section_id)
        if not section:
            raise ValueError("Section not found")
        require_owner(db, section.institute_id, user["id"])
        assign_subject_student(db, section_id, subject_id, body.userId)
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return StudentSubjectOut(userId=body.userId)


@app.delete(
    "/v1/sections/{section_id}/subjects/{subject_id}/students/{student_id}",
    status_code=204,
)
def remove_subject_student(
    section_id: str,
    subject_id: str,
    student_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_education_subscription),
):
    try:
        section = db.get(Section, section_id)
        if not section:
            raise ValueError("Section not found")
        require_owner(db, section.institute_id, user["id"])
        unassign_subject_student(db, section_id, subject_id, student_id)
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


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
        require_manage(db, section.institute_id, user["id"])
        row = assign_section_member(db, section_id, body.userId, body.memberType)
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return {"sectionId": section_id, "userId": row.user_id, "memberType": row.member_type}


@app.post(
    "/v1/sections/{section_id}/members/bulk",
    response_model=SectionMemberBulkOut,
    status_code=201,
)
def bulk_assign_section_members_route(
    section_id: str,
    body: SectionMemberBulkIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_education_subscription),
):
    section = db.get(Section, section_id)
    if not section:
        raise HTTPException(status_code=404, detail="Section not found")
    try:
        require_manage(db, section.institute_id, user["id"])
        result = bulk_assign_section_members(
            db,
            section_id,
            [item.model_dump() for item in body.members],
        )
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e)) from e
    return SectionMemberBulkOut(**result)


@app.post(
    "/v1/institutes/{institute_id}/enrollments/transfer",
    response_model=EnrollmentTransferOut,
)
def transfer_enrollment(
    institute_id: str,
    body: EnrollmentTransferIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_education_subscription),
):
    try:
        member = require_membership(db, institute_id, user["id"])
        if member.role not in MANAGE_ROLES and member.role != "principal":
            raise PermissionError("Owner or principal role required")
        data = transfer_student_enrollment(
            db,
            institute_id,
            body.studentId,
            body.toSectionId,
            body.reason,
        )
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return EnrollmentTransferOut(**data)


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
        require_manage(db, section.institute_id, user["id"])
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


@app.get("/v1/sections/{section_id}/class-dashboard", response_model=SectionClassDashboardOut)
def section_class_dashboard(
    section_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_education_subscription),
):
    try:
        return get_section_class_dashboard(db, section_id, user["id"])
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@app.get("/v1/sections/{section_id}/student-insights")
def section_student_insights(
    section_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_education_subscription),
):
    try:
        return get_student_insights(db, section_id, user["id"])
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@app.get("/v1/sections/{section_id}/students/{student_id}/performance")
def student_performance(
    section_id: str,
    student_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_education_subscription),
):
    try:
        return get_student_performance(db, section_id, student_id, user["id"])
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@app.get("/v1/sections/{section_id}/students/{student_id}/attendance")
def student_attendance_history(
    section_id: str,
    student_id: str,
    start_date: date | None = None,
    end_date: date | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(require_education_subscription),
):
    end = end_date or date.today()
    start = start_date or end - timedelta(days=365)
    if start > end:
        raise HTTPException(status_code=400, detail="Start date must be before end date")
    try:
        return get_student_attendance(db, section_id, student_id, user["id"], start, end)
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


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
        require_owner(db, section.institute_id, user["id"])
        assign_section_member(db, section_id, body.userId, "teacher")
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return {"sectionId": section_id, "userId": body.userId, "type": "teacher"}


@app.get("/v1/sections/{section_id}/attendance/sheet", response_model=AttendanceSheetOut)
def section_attendance_sheet(
    section_id: str,
    days: int = Query(7, ge=1, le=366),
    end_date: date | None = Query(None, alias="endDate"),
    summary_period: str = Query("academic_year", alias="summaryPeriod"),
    db: Session = Depends(get_db),
    user: User = Depends(require_education_subscription),
):
    try:
        return get_section_attendance_sheet(
            db,
            section_id,
            user["id"],
            days=days,
            end_date=end_date,
            summary_period=summary_period,
        )
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@app.get(
    "/v1/sections/{section_id}/leave-requests",
    response_model=list[StudentLeaveRequestOut],
)
def section_leave_requests(
    section_id: str,
    status: str | None = Query(None, pattern="^(pending|approved|rejected)$"),
    db: Session = Depends(get_db),
    user: User = Depends(require_education_subscription),
):
    try:
        return list_section_leave_requests(db, section_id, user["id"], status=status)
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@app.put("/v1/sections/{section_id}/attendance/present-sync", response_model=list[AttendanceOut])
def sync_present_attendance(
    section_id: str,
    body: AttendancePresentSyncIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_education_subscription),
):
    try:
        save_present_only_attendance(
            db,
            section_id,
            user["id"],
            body.attendanceDate,
            body.presentStudentIds,
            body.excusedStudentIds,
            body.publishState,
        )
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    return list_attendance(section_id, body.attendanceDate, db, user)


@app.get("/v1/sections/{section_id}/attendance", response_model=list[AttendanceOut])
def list_attendance(
    section_id: str,
    attendance_date: date | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(require_education_subscription),
):
    section = db.get(Section, section_id)
    if not section:
        raise HTTPException(status_code=404, detail="Section not found")
    try:
        require_section_access(db, section_id, user["id"])
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    query = select(AttendanceRecord).where(
        AttendanceRecord.section_id == section_id,
        AttendanceRecord.attendance_date == (attendance_date or date.today()),
    )
    member = get_membership(db, section.institute_id, user["id"])
    if member and member.role == "student":
        query = query.where(AttendanceRecord.student_id == user["id"])
    rows = db.scalars(query.order_by(AttendanceRecord.student_id))
    return [
        AttendanceOut(
            studentId=row.student_id,
            attendanceDate=row.attendance_date,
            status=row.status,
            markedBy=row.marked_by,
        )
        for row in rows
    ]


@app.put("/v1/sections/{section_id}/attendance", response_model=list[AttendanceOut])
def save_attendance(
    section_id: str,
    body: AttendanceUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require_education_subscription),
):
    try:
        section = require_section_teacher(db, section_id, user["id"])
        assert_can_mark_attendance(db, section, user["id"], body.attendanceDate)
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e

    student_ids = set(
        db.scalars(
            select(SectionMember.user_id).where(
                SectionMember.section_id == section_id,
                SectionMember.member_type == "student",
            )
        )
    )
    if any(record.studentId not in student_ids for record in body.records):
        raise HTTPException(status_code=400, detail="Attendance includes an unassigned student")

    for record in body.records:
        existing = db.scalar(
            select(AttendanceRecord).where(
                AttendanceRecord.section_id == section_id,
                AttendanceRecord.student_id == record.studentId,
                AttendanceRecord.attendance_date == body.attendanceDate,
            )
        )
        if existing:
            existing.status = record.status
            existing.marked_by = user["id"]
        else:
            db.add(
                AttendanceRecord(
                    section_id=section_id,
                    student_id=record.studentId,
                    attendance_date=body.attendanceDate,
                    status=record.status,
                    marked_by=user["id"],
                )
            )
    db.commit()
    return list_attendance(section_id, body.attendanceDate, db, user)


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
        require_owner(db, section.institute_id, user["id"])
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
        require_daily_note_editor(db, section_id, user["id"])
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
        assignment_type=body.assignmentType,
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
        assignmentType=assignment.assignment_type,
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
        AssignmentOut(
            id=a.id,
            title=a.title,
            description=a.description,
            assignmentType=a.assignment_type,
            dueDate=a.due_date,
        )
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


def _assignment_http_errors(fn):
    try:
        return fn()
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@app.get("/v1/sections/{section_id}/assignment-works")
def section_assignment_works_list(
    section_id: str,
    bucket: str | None = Query(None),
    db: Session = Depends(get_db),
    user: User = Depends(require_education_subscription),
):
    return _assignment_http_errors(
        lambda: list_teacher_works(db, section_id, user["id"], bucket)
    )


@app.post("/v1/sections/{section_id}/assignment-works", status_code=201)
def section_assignment_works_create(
    section_id: str,
    body: AssignmentWorkCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_education_subscription),
):
    return _assignment_http_errors(
        lambda: create_work(db, section_id, user["id"], body.model_dump())
    )


@app.get("/v1/sections/{section_id}/assignment-works/assigned")
def section_assignment_works_assigned(
    section_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_education_subscription),
):
    return _assignment_http_errors(lambda: list_assigned_student(db, section_id, user["id"]))


@app.get("/v1/assignment-works/{assignment_id}")
def assignment_work_get(
    assignment_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_education_subscription),
):
    return _assignment_http_errors(lambda: get_work(db, assignment_id, user["id"]))


@app.patch("/v1/assignment-works/{assignment_id}")
def assignment_work_patch(
    assignment_id: str,
    body: AssignmentWorkPatch,
    db: Session = Depends(get_db),
    user: User = Depends(require_education_subscription),
):
    return _assignment_http_errors(
        lambda: patch_work(db, assignment_id, user["id"], body.model_dump(exclude_unset=True))
    )


@app.get("/v1/assignment-works/{assignment_id}/questions")
def assignment_work_questions_get(
    assignment_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_education_subscription),
):
    return _assignment_http_errors(lambda: list_questions_teacher(db, assignment_id, user["id"]))


@app.put("/v1/assignment-works/{assignment_id}/questions")
def assignment_work_questions_put(
    assignment_id: str,
    body: AssignmentQuestionsReplaceIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_education_subscription),
):
    return _assignment_http_errors(
        lambda: replace_questions(
            db, assignment_id, user["id"], [q.model_dump() for q in body.questions]
        )
    )


@app.post("/v1/assignment-works/{assignment_id}/publish")
def assignment_work_publish(
    assignment_id: str,
    body: AssignmentWorkPublishIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_education_subscription),
):
    from app.services.section_assignments import _parse_dt

    publish_at = _parse_dt(body.publishAt) if body.publishAt else None
    return _assignment_http_errors(
        lambda: publish_work(db, assignment_id, user["id"], publish_at)
    )


@app.post("/v1/assignment-works/{assignment_id}/unpublish")
def assignment_work_unpublish(
    assignment_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_education_subscription),
):
    return _assignment_http_errors(lambda: unpublish_work(db, assignment_id, user["id"]))


@app.get("/v1/assignment-works/{assignment_id}/submissions")
def assignment_work_submissions(
    assignment_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_education_subscription),
):
    return _assignment_http_errors(lambda: list_submissions(db, assignment_id, user["id"]))


@app.post("/v1/assignment-works/{assignment_id}/attempts")
def assignment_work_attempt_start(
    assignment_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_education_subscription),
):
    return _assignment_http_errors(lambda: get_or_create_attempt(db, assignment_id, user["id"]))


@app.get("/v1/assignment-works/{assignment_id}/attempts/me")
def assignment_work_attempt_me(
    assignment_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_education_subscription),
):
    return _assignment_http_errors(lambda: get_or_create_attempt(db, assignment_id, user["id"]))


@app.patch("/v1/assignment-works/{assignment_id}/attempts/me/responses")
def assignment_work_attempt_responses(
    assignment_id: str,
    body: AssignmentResponsesPatchIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_education_subscription),
):
    return _assignment_http_errors(
        lambda: save_responses(db, assignment_id, user["id"], body.answers)
    )


@app.post("/v1/assignment-works/{assignment_id}/attempts/me/submit")
def assignment_work_attempt_submit(
    assignment_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_education_subscription),
):
    return _assignment_http_errors(lambda: submit_attempt(db, assignment_id, user["id"]))


@app.patch("/v1/assignment-works/{assignment_id}/attempts/{attempt_id}/grade")
def assignment_work_attempt_grade(
    assignment_id: str,
    attempt_id: str,
    body: AssignmentGradeIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_education_subscription),
):
    return _assignment_http_errors(
        lambda: grade_attempt(
            db,
            assignment_id,
            attempt_id,
            user["id"],
            body.model_dump(),
        )
    )


@app.get("/v1/guardians/me/children/{student_id}/assignment-works")
def guardian_child_assignment_works(
    student_id: str,
    section_id: str = Query(...),
    db: Session = Depends(get_db),
    user: User = Depends(require_education_subscription),
):
    """Guardian read path (phase 6): returns published graded works when scores_visible."""
    raise HTTPException(
        status_code=501,
        detail="Guardian assignment read not enabled; use student account or enable in a future release.",
    )


@app.post("/v1/assignment-works/{assignment_id}/llm-variants")
def assignment_work_llm_variants(
    assignment_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_education_subscription),
):
    if not settings.assignment_llm_rewrite_enabled:
        raise HTTPException(status_code=501, detail="LLM paraphrase is disabled")
    raise HTTPException(status_code=501, detail="LLM paraphrase not implemented")


@app.get("/v1/institutes/{institute_id}/attendance/summary", response_model=AttendanceSummaryOut)
def attendance_summary(
    institute_id: str,
    day: date | None = None,
    campus_id: str | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(require_education_subscription),
):
    try:
        return get_attendance_summary(db, institute_id, user["id"], day or date.today(), campus_id)
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e)) from e


@app.get("/v1/institutes/{institute_id}/exams", response_model=list[ExamOut])
def list_exams(
    institute_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_education_subscription),
):
    try:
        return [ExamOut(**exam_service.exam_to_dict(row)) for row in exam_service.list_exams(db, institute_id, user["id"])]
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e)) from e


@app.post("/v1/institutes/{institute_id}/exams", response_model=ExamOut, status_code=201)
def create_exam(
    institute_id: str,
    body: ExamCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_education_subscription),
):
    try:
        exam = exam_service.create_exam(
            db,
            institute_id,
            user["id"],
            name=body.name,
            academic_year_id=body.academicYearId,
            section_id=body.sectionId,
            subject_id=body.subjectId,
            max_marks=body.maxMarks,
            scheduled_at=body.scheduledAt,
        )
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e)) from e
    return ExamOut(**exam_service.exam_to_dict(exam))


@app.get("/v1/institutes/{institute_id}/exams/{exam_id}", response_model=ExamOut)
def get_exam(
    institute_id: str,
    exam_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_education_subscription),
):
    try:
        exam = exam_service.get_exam(db, exam_id, user["id"])
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    if exam.institute_id != institute_id:
        raise HTTPException(status_code=404, detail="Exam not found")
    return ExamOut(**exam_service.exam_to_dict(exam))


@app.put("/v1/institutes/{institute_id}/exams/{exam_id}", response_model=ExamOut)
def update_exam(
    institute_id: str,
    exam_id: str,
    body: ExamUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require_education_subscription),
):
    try:
        exam = exam_service.update_exam(
            db,
            exam_id,
            user["id"],
            name=body.name,
            section_id=body.sectionId,
            subject_id=body.subjectId,
            max_marks=body.maxMarks,
            scheduled_at=body.scheduledAt,
        )
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    if exam.institute_id != institute_id:
        raise HTTPException(status_code=404, detail="Exam not found")
    return ExamOut(**exam_service.exam_to_dict(exam))


@app.delete("/v1/institutes/{institute_id}/exams/{exam_id}", status_code=204)
def delete_exam_route(
    institute_id: str,
    exam_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_education_subscription),
):
    try:
        exam = exam_service.get_exam(db, exam_id, user["id"])
        if exam.institute_id != institute_id:
            raise HTTPException(status_code=404, detail="Exam not found")
        exam_service.delete_exam(db, exam_id, user["id"])
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@app.get("/v1/exams/{exam_id}/marks", response_model=list[MarkEntryOut])
def get_exam_marks(
    exam_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_education_subscription),
):
    try:
        rows = exam_service.list_marks(db, exam_id, user["id"])
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    return [MarkEntryOut(**exam_service.mark_to_dict(row)) for row in rows]


@app.put("/v1/exams/{exam_id}/marks", response_model=list[MarkEntryOut])
def put_exam_marks(
    exam_id: str,
    body: MarksUpsert,
    db: Session = Depends(get_db),
    user: User = Depends(require_education_subscription),
):
    try:
        rows = exam_service.upsert_marks(
            db, exam_id, user["id"], [entry.model_dump() for entry in body.entries]
        )
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return [MarkEntryOut(**exam_service.mark_to_dict(row)) for row in rows]


@app.post("/v1/exams/{exam_id}/publish", response_model=ExamOut)
def publish_exam(
    exam_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_education_subscription),
):
    try:
        exam = exam_service.publish_exam(db, exam_id, user["id"])
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    return ExamOut(**exam_service.exam_to_dict(exam))


@app.get("/v1/institutes/{institute_id}/fee-structures", response_model=list[FeeStructureOut])
def list_fee_structures(
    institute_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_education_subscription),
):
    try:
        rows = fee_service.list_fee_structures(db, institute_id, user["id"])
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e)) from e
    return [
        FeeStructureOut(
            id=row.id,
            instituteId=row.institute_id,
            academicYearId=row.academic_year_id,
            name=row.name,
            amountPaise=row.amount_paise,
        )
        for row in rows
    ]


@app.post("/v1/institutes/{institute_id}/fee-structures", response_model=FeeStructureOut, status_code=201)
def create_fee_structure(
    institute_id: str,
    body: FeeStructureCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_education_subscription),
):
    try:
        row = fee_service.create_fee_structure(
            db, institute_id, user["id"], body.name, body.amountPaise, body.academicYearId
        )
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e)) from e
    return FeeStructureOut(
        id=row.id,
        instituteId=row.institute_id,
        academicYearId=row.academic_year_id,
        name=row.name,
        amountPaise=row.amount_paise,
    )


@app.post("/v1/institutes/{institute_id}/student-fees", response_model=StudentFeeDueOut, status_code=201)
def assign_student_fee(
    institute_id: str,
    body: StudentFeeAssign,
    db: Session = Depends(get_db),
    user: User = Depends(require_education_subscription),
):
    try:
        row = fee_service.assign_student_fee(
            db, institute_id, user["id"], body.studentId, body.feeStructureId, body.amountPaise
        )
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    return StudentFeeDueOut(
        studentId=row.student_id,
        feeStructureId=row.fee_structure_id,
        amountPaise=row.amount_paise,
        paidPaise=row.paid_paise,
        balancePaise=max(row.amount_paise - row.paid_paise, 0),
    )


@app.get("/v1/institutes/{institute_id}/fees/dues", response_model=list[StudentFeeDueOut])
def list_fee_dues(
    institute_id: str,
    student_id: str | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(require_education_subscription),
):
    try:
        rows = fee_service.list_dues(db, institute_id, user["id"], student_id)
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e)) from e
    return [StudentFeeDueOut(**row) for row in rows]


@app.post("/v1/institutes/{institute_id}/fees/payments", response_model=PaymentOut, status_code=201)
def record_fee_payment(
    institute_id: str,
    body: PaymentCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_education_subscription),
):
    try:
        payment = fee_service.record_payment(
            db,
            institute_id,
            user["id"],
            body.studentId,
            body.amountPaise,
            body.method,
            body.reference,
        )
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return PaymentOut(
        id=payment.id,
        instituteId=payment.institute_id,
        studentId=payment.student_id,
        amountPaise=payment.amount_paise,
        method=payment.method,
        reference=payment.reference,
        receiptNumber=payment.receipt_number,
        recordedBy=payment.recorded_by,
        createdAt=payment.created_at,
    )


@app.get("/v1/institutes/{institute_id}/fee-receipts/{receipt_id}", response_model=PaymentOut)
def get_fee_receipt(
    institute_id: str,
    receipt_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_education_subscription),
):
    try:
        payment = fee_service.get_receipt(db, institute_id, receipt_id, user["id"])
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    return PaymentOut(
        id=payment.id,
        instituteId=payment.institute_id,
        studentId=payment.student_id,
        amountPaise=payment.amount_paise,
        method=payment.method,
        reference=payment.reference,
        receiptNumber=payment.receipt_number,
        recordedBy=payment.recorded_by,
        createdAt=payment.created_at,
    )


@app.get("/v1/institutes/{institute_id}/calendar-events", response_model=list[CalendarEventOut])
def list_calendar_events(
    institute_id: str,
    campus_id: str | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(require_education_subscription),
):
    try:
        rows = notice_service.list_calendar_events(db, institute_id, user["id"], campus_id)
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e)) from e
    return [CalendarEventOut(**notice_service.calendar_event_to_dict(row)) for row in rows]


@app.post("/v1/institutes/{institute_id}/calendar-events", response_model=CalendarEventOut, status_code=201)
def create_calendar_event(
    institute_id: str,
    body: CalendarEventCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_education_subscription),
):
    try:
        row = notice_service.create_calendar_event(
            db,
            institute_id,
            user["id"],
            body.title,
            body.eventDate,
            body.description,
            body.branchId,
            body.audience,
            body.targetSectionIds,
            body.targetUserIds,
            body.studentGender,
            body.distributionListId,
        )
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return CalendarEventOut(**notice_service.calendar_event_to_dict(row))


@app.post(
    "/v1/institutes/{institute_id}/guardian-links/seed",
    response_model=GuardianLinksSeedOut,
)
def seed_guardian_links(
    institute_id: str,
    body: GuardianLinksSeedIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_education_subscription),
):
    try:
        require_owner(db, institute_id, user["id"])
        pairs = [(link.guardianUserId, link.studentUserIds) for link in body.links]
        count = set_demo_guardian_links(db, institute_id, pairs)
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return GuardianLinksSeedOut(guardiansUpdated=count)


@app.get("/v1/users/me/guardian-children", response_model=GuardianChildrenOut)
def my_guardian_children(
    institute_id: str | None = Query(None, alias="instituteId"),
    db: Session = Depends(get_db),
    user: User = Depends(require_education_subscription),
):
    try:
        rows = list_guardian_children(
            db,
            user["id"],
            user["token"],
            institute_id=institute_id,
        )
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e)) from e
    return GuardianChildrenOut(children=[GuardianChildOut(**row) for row in rows])


@app.get(
    "/v1/institutes/{institute_id}/parent/children/{child_id}/threads",
    response_model=list[ParentThreadOut],
)
def list_parent_child_threads(
    institute_id: str,
    child_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_education_subscription),
):
    try:
        rows = parent_messaging.list_threads(
            db, institute_id, user["id"], child_id, user["token"]
        )
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e)) from e
    return [ParentThreadOut(**row) for row in rows]


@app.post(
    "/v1/institutes/{institute_id}/parent/children/{child_id}/threads",
    response_model=ParentThreadOut,
    status_code=201,
)
def create_parent_child_thread(
    institute_id: str,
    child_id: str,
    body: ParentThreadCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_education_subscription),
):
    try:
        row = parent_messaging.create_thread(
            db,
            institute_id,
            user["id"],
            child_id,
            user["token"],
            subject=body.subject,
            initial_message=body.initialMessage,
        )
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e)) from e
    return ParentThreadOut(**row)


@app.post(
    "/v1/institutes/{institute_id}/parent/children/{child_id}/threads/{thread_id}/messages",
    response_model=ParentMessageOut,
    status_code=201,
)
def post_parent_thread_message(
    institute_id: str,
    child_id: str,
    thread_id: str,
    body: ParentMessageCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_education_subscription),
):
    try:
        row = parent_messaging.post_message(
            db,
            institute_id,
            user["id"],
            child_id,
            thread_id,
            user["token"],
            body=body.body,
        )
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e)) from e
    return ParentMessageOut(**row)


@app.get("/v1/institutes/{institute_id}/reports/{report_type}")
def download_report(
    institute_id: str,
    report_type: str,
    month: date | None = None,
    campus_id: str | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(require_education_subscription),
):
    try:
        csv_body = report_service.build_report(
            db, institute_id, user["id"], report_type, month=month, campus_id=campus_id
        )
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    filename = f"{report_type}-report.csv"
    return Response(
        content=csv_body,
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
