from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator


class InstituteCreate(BaseModel):
    name: str = Field(min_length=2, max_length=200)
    contactName: str = Field(min_length=2, max_length=200)
    phone: str = Field(max_length=32)
    address: str = Field(min_length=2, max_length=500)
    city: str = Field(min_length=2, max_length=100)
    state: str = Field(default="", max_length=100)
    postalCode: str = Field(default="", max_length=20)

    @field_validator("name", "contactName", "phone", "address", "city", "state", "postalCode", mode="before")
    @classmethod
    def strip_text(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip()
        return value

    @field_validator("phone")
    @classmethod
    def require_phone_digits(cls, value: str) -> str:
        digits = "".join(ch for ch in value if ch.isdigit())
        if len(digits) < 7:
            raise ValueError("Phone needs at least 7 digits")
        return value


class InstituteOut(BaseModel):
    id: str
    name: str
    joinCode: str
    role: str


class InstituteStats(BaseModel):
    staffCount: int
    studentCount: int
    sectionCount: int
    branchCount: int


class AcademicTermOut(BaseModel):
    id: str
    name: str
    startDate: date
    endDate: date
    weightPercent: int


class AcademicYearOut(BaseModel):
    id: str
    label: str
    startDate: date
    endDate: date
    board: str
    termCount: int
    gradingScale: str
    medium: str
    isActive: bool
    terms: list[AcademicTermOut]


class AcademicYearUpdate(BaseModel):
    label: str = Field(min_length=4, max_length=32)
    startDate: date
    endDate: date
    board: str = Field(min_length=2, max_length=32)
    termCount: int = Field(ge=1, le=4)
    gradingScale: str = Field(min_length=2, max_length=64)
    medium: str = Field(min_length=2, max_length=64)


class InstituteDetailOut(BaseModel):
    id: str
    name: str
    joinCode: str
    role: str
    createdAt: datetime
    stats: InstituteStats


class JoinInstitute(BaseModel):
    joinCode: str


class MemberOut(BaseModel):
    userId: str
    role: str
    firstName: str = ""
    lastName: str = ""
    displayName: str = ""
    email: str = ""
    username: str = ""
    dateOfBirth: date | None = None


class MemberAdd(BaseModel):
    userId: str
    role: str = Field(pattern="^(admin|principal|teacher|lecturer|professor|student|parent)$")


class MemberRoleUpdate(BaseModel):
    role: str = Field(pattern="^(admin|principal|teacher|lecturer|professor|student|parent)$")


class MemberProfileOut(BaseModel):
    userId: str
    role: str
    displayName: str = ""
    email: str = ""
    sections: list[dict]
    branches: list[str]
    dateOfBirth: date | None = None
    gender: str | None = None
    classLabel: str | None = None
    admissionNo: str | None = None


class MembersRosterItemOut(BaseModel):
    id: str
    userId: str | None = None
    role: str | None = None
    kind: str | None = None
    memberType: str | None = None
    status: str | None = None
    className: str | None = None
    sectionName: str | None = None
    firstName: str = ""
    lastName: str = ""
    displayName: str = ""
    email: str = ""
    username: str = ""
    message: str | None = None
    requestedAt: str | None = None
    invitedAt: str | None = None


class MembersRosterTabCountsOut(BaseModel):
    all: int
    staff: int
    students: int
    parents: int
    requests: int
    invitations: int


class MembersRosterOut(BaseModel):
    items: list[MembersRosterItemOut]
    total: int
    tabCounts: MembersRosterTabCountsOut


class JoinCodeRegenerateOut(BaseModel):
    joinCode: str


class SubjectTeacherColumnOut(BaseModel):
    subjectId: str
    name: str
    offeredIn: list[str] = Field(default_factory=list)


class SubjectTeacherCellOut(BaseModel):
    subjectId: str
    teacherId: str | None = None
    teacherName: str | None = None
    periodsPerWeek: int | None = None
    isGraded: bool = False
    sectionLabels: list[str] | None = None


class SubjectTeacherMatrixRowOut(BaseModel):
    sectionId: str | None = None
    classId: str | None = None
    teacherId: str | None = None
    label: str
    cells: list[SubjectTeacherCellOut]


class SubjectTeacherMatrixOut(BaseModel):
    columns: list[SubjectTeacherColumnOut]
    rows: list[SubjectTeacherMatrixRowOut]


class SubjectTeacherPanelSubjectOut(BaseModel):
    subjectId: str
    name: str
    sectionsCount: int


class SubjectTeacherPanelItemOut(BaseModel):
    personId: str
    name: str = ""
    subjects: list[SubjectTeacherPanelSubjectOut]
    periodsPerWeek: int
    weeklyLimit: int
    classTeacherOf: list[str] = Field(default_factory=list)


class SubjectTeacherPanelOut(BaseModel):
    items: list[SubjectTeacherPanelItemOut]


class SubjectTeacherChecksOut(BaseModel):
    unassignedCount: int
    overLimitCount: int
    noClassCount: int
    unassignedCells: list[dict]
    overLimitTeachers: list[str]
    noClassTeachers: list[str]


class SubjectTeacherCopyIn(BaseModel):
    sourceSectionId: str
    targetSectionIds: list[str] = Field(min_length=1)
    replaceExisting: bool = False


class SubjectTeacherCopyOut(BaseModel):
    changes: list[dict]
    changeCount: int


class SubjectTeacherAssignmentSaveIn(BaseModel):
    sectionId: str
    subjectId: str
    teacherId: str | None = None


class SubjectTeacherAssignmentsSaveIn(BaseModel):
    assignments: list[SubjectTeacherAssignmentSaveIn]


class BranchTeacherBrief(BaseModel):
    userId: str
    role: str
    firstName: str = ""
    lastName: str = ""
    displayName: str = ""
    email: str = ""
    username: str = ""
    dateOfBirth: date | None = None


class BranchStudentBrief(BaseModel):
    userId: str
    role: str
    firstName: str = ""
    lastName: str = ""
    displayName: str = ""
    email: str = ""
    username: str = ""
    dateOfBirth: date | None = None


class UpcomingEventOut(BaseModel):
    type: str
    title: str
    dueDate: str
    sectionName: str
    branchName: str | None = None


class AssignmentResultOut(BaseModel):
    assignmentId: str
    title: str
    sectionName: str
    dueDate: str | None = None
    submittedCount: int
    enrolledStudents: int
    completionPercent: int


class BranchInsightsOut(BaseModel):
    openAssignments: int
    averageCompletionPercent: int | None = None
    recentResults: list[AssignmentResultOut]


class BranchSummaryOut(BaseModel):
    id: str
    name: str
    isPrimary: bool
    address: str
    city: str
    state: str = ""
    postalCode: str = ""
    email: str = ""
    phone: str = ""
    teacherCount: int
    studentCount: int
    teachers: list[BranchTeacherBrief]
    students: list[BranchStudentBrief]
    insights: BranchInsightsOut


class InstituteSummaryOut(BaseModel):
    branchCount: int
    branches: list[BranchSummaryOut]
    upcomingEvents: list[UpcomingEventOut]
    pendingInvitations: int = 0


class OverviewStatsOut(BaseModel):
    students: int | None = None
    staff: int | None = None
    attendancePercent: int | None = None
    unmarkedClasses: int | None = None
    assignmentCompletionPercent: int | None = None
    pendingApprovals: int | None = None


class OverviewAttentionOut(BaseModel):
    kind: str
    count: int
    label: str


class OverviewAttendanceOut(BaseModel):
    sectionId: str
    label: str
    marked: bool
    present: int
    total: int
    percent: int | None = None


class OverviewUpcomingOut(BaseModel):
    id: str
    type: str
    title: str
    date: date
    sectionId: str


class OverviewPostOut(BaseModel):
    id: str
    title: str
    body: str
    createdAt: datetime


class OwnerOverviewOut(BaseModel):
    stats: OverviewStatsOut
    attention: list[OverviewAttentionOut]
    attendanceByClass: list[OverviewAttendanceOut]
    upcoming: list[OverviewUpcomingOut]
    posts: list[OverviewPostOut]


class InvitationCreate(BaseModel):
    userId: str
    role: str = Field(pattern="^(teacher|student|parent)$")


class InvitationOut(BaseModel):
    id: str
    instituteId: str
    instituteName: str | None = None
    inviteeUserId: str | None = None
    inviteeEmail: str = ""
    inviteeFirstName: str = ""
    inviteeLastName: str = ""
    inviteeDisplayName: str = ""
    inviteeUsername: str = ""
    role: str
    status: str
    invitedBy: str
    createdAt: datetime


class InvitationRespondOut(BaseModel):
    instituteId: str
    role: str


class JoinRequestCreate(BaseModel):
    requestedRole: str = Field(pattern="^(teacher|lecturer|professor|student|parent)$")
    message: str = ""


class JoinRequestOut(BaseModel):
    id: str
    instituteId: str
    instituteName: str | None = None
    userId: str
    userEmail: str | None = None
    firstName: str = ""
    lastName: str = ""
    displayName: str = ""
    username: str = ""
    requestedRole: str
    message: str
    status: str
    createdAt: datetime


class JoinRequestRespondOut(BaseModel):
    instituteId: str
    role: str


class InstituteLookupOut(BaseModel):
    id: str
    name: str


class UserSearchOut(BaseModel):
    userId: str
    email: str
    username: str
    displayName: str


class InstituteProfileOut(BaseModel):
    id: str
    name: str
    joinCode: str
    description: str = ""
    email: str = ""
    phone: str = ""
    website: str = ""
    address: str = ""
    city: str = ""
    state: str = ""
    postalCode: str = ""
    contactName: str = ""


class InstituteProfileUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=200)
    description: str | None = None
    email: str | None = None
    phone: str | None = None
    website: str | None = None
    address: str | None = None
    city: str | None = None
    state: str | None = None
    postalCode: str | None = None


class CampusScopeBranchOut(BaseModel):
    id: str
    name: str
    isPrimary: bool


class CampusScopeOut(BaseModel):
    branches: list[CampusScopeBranchOut]
    canSwitch: bool
    defaultBranchId: str | None = None


class BranchCreate(BaseModel):
    name: str = Field(min_length=2, max_length=200)
    address: str = ""
    city: str = ""
    state: str = ""
    postalCode: str = ""
    email: str = ""
    phone: str = ""
    isPrimary: bool = False


class BranchUpdate(BaseModel):
    name: str | None = None
    address: str | None = None
    city: str | None = None
    state: str | None = None
    postalCode: str | None = None
    email: str | None = None
    phone: str | None = None
    isPrimary: bool | None = None


class BranchOut(BaseModel):
    id: str
    name: str
    address: str
    city: str
    state: str = ""
    postalCode: str = ""
    email: str = ""
    phone: str = ""
    isPrimary: bool
    sectionCount: int = 0


class SectionCreate(BaseModel):
    name: str
    className: str = ""
    branchId: str | None = None


class SectionOut(BaseModel):
    id: str
    name: str
    className: str
    branchId: str | None = None
    branchName: str | None = None
    classTeacherUserId: str | None = None


class SectionClassTeacherUpdate(BaseModel):
    userId: str | None = None


class AssignMember(BaseModel):
    userId: str


class SectionMemberAssign(BaseModel):
    userId: str
    memberType: str = Field(pattern="^(teacher|student)$")


class SubjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)

    @field_validator("name")
    @classmethod
    def require_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Subject name is required")
        return value


class SubjectOut(BaseModel):
    id: str
    name: str


class ActivityCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)

    @field_validator("name")
    @classmethod
    def require_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Activity name is required")
        return value


class ActivityOut(BaseModel):
    id: str
    name: str


class RoomCreate(BaseModel):
    name: str = Field(min_length=1, max_length=30)

    @field_validator("name")
    @classmethod
    def require_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Room name is required")
        return value[:30]


class RoomOut(BaseModel):
    id: str
    name: str


class SectionSubjectAssign(BaseModel):
    subjectId: str
    weeklyPeriods: int | None = Field(default=None, ge=1, le=40)


class SectionMemberBulkItem(BaseModel):
    userId: str
    memberType: str = Field(pattern="^(teacher|student)$")


class SectionMemberBulkIn(BaseModel):
    members: list[SectionMemberBulkItem] = Field(min_length=1, max_length=100)


class SectionMemberBulkSkipped(BaseModel):
    userId: str
    reason: str


class SectionMemberBulkOut(BaseModel):
    added: int
    skipped: list[SectionMemberBulkSkipped] = Field(default_factory=list)


class EnrollmentTransferIn(BaseModel):
    studentId: str
    toSectionId: str
    reason: str = Field(default="", max_length=500)
    effectiveDate: date | None = None


class EnrollmentTransferOut(BaseModel):
    studentId: str
    fromSectionId: str | None = None
    toSectionId: str
    reason: str = ""


class TeacherSubjectAssign(BaseModel):
    userId: str


class TeacherSubjectOut(BaseModel):
    userId: str


class StudentSubjectAssign(BaseModel):
    userId: str


class StudentSubjectOut(BaseModel):
    userId: str


class SectionSubjectOut(BaseModel):
    id: str
    name: str
    weeklyPeriods: int | None = None
    teachers: list[TeacherSubjectOut] = Field(default_factory=list)
    students: list[StudentSubjectOut] = Field(default_factory=list)


class SectionSubjectWeeklyPeriodsPatch(BaseModel):
    weeklyPeriods: int | None = Field(default=None, ge=1, le=40)


class SyllabusNodeOut(BaseModel):
    id: str
    title: str
    weightPercent: float
    sortOrder: int
    completedPercent: float
    effectiveCompletedPercent: float
    isLeaf: bool
    canEditCompletion: bool
    children: list["SyllabusNodeOut"] = Field(default_factory=list)


class SyllabusTreeOut(BaseModel):
    subjectId: str
    subjectName: str
    subjectTotalCompletedPercent: float
    nodes: list[SyllabusNodeOut] = Field(default_factory=list)


class SyllabusSubjectSummaryOut(BaseModel):
    subjectId: str
    subjectName: str
    totalCompletedPercent: float
    nodeCount: int


class SyllabusNodeCreate(BaseModel):
    parentId: str | None = None
    title: str
    weightPercent: float = Field(gt=0, le=100)
    sortOrder: int | None = None


class SyllabusNodePatch(BaseModel):
    title: str | None = None
    weightPercent: float | None = Field(default=None, gt=0, le=100)
    parentId: str | None = None
    sortOrder: int | None = None


class SyllabusCompletionPatch(BaseModel):
    completedPercent: float = Field(ge=0, le=100)


class SyllabusCopyIn(BaseModel):
    sourceSectionId: str
    targetSectionIds: list[str] = Field(min_length=1)


class SyllabusCopyOut(BaseModel):
    subjectsCopied: int
    nodesCopied: int
    targetCount: int


class SyllabusWeightItem(BaseModel):
    nodeId: str
    weightPercent: float = Field(gt=0, le=100)


class SyllabusWeightsPatch(BaseModel):
    weights: list[SyllabusWeightItem] = Field(min_length=1)


SyllabusNodeOut.model_rebuild()


class ScheduleSettingsOut(BaseModel):
    timezone: str
    schoolStart: str
    schoolEnd: str
    weekdays: list[int]


class ScheduleSlotOut(BaseModel):
    id: str
    label: str
    kind: str
    start: str
    end: str
    position: int
    dayOfWeek: int | None = None
    activityId: str | None = None


class TimetableEntryOut(BaseModel):
    id: str
    dayOfWeek: int
    slotId: str
    sectionId: str
    subjectId: str
    teacherId: str | None = None
    room: str | None = None
    locked: bool = False


class SpecialDayActivityOut(BaseModel):
    id: str
    activityId: str
    start: str
    end: str
    position: int
    sectionIds: list[str]
    teacherIds: list[str]


class SpecialDayOut(BaseModel):
    id: str
    date: date
    label: str
    replaceRegular: bool
    activities: list[SpecialDayActivityOut]


class ScheduleOut(BaseModel):
    instituteId: str
    revision: int
    publishedAt: datetime | None = None
    draftSavedAt: datetime | None = None
    changedSincePublish: bool = False
    settings: ScheduleSettingsOut
    slots: list[ScheduleSlotOut]
    entries: list[TimetableEntryOut]
    specialDays: list[SpecialDayOut] = Field(default_factory=list)


class ScheduleSettingsIn(BaseModel):
    timezone: str = "Asia/Kolkata"
    schoolStart: str = Field(default="08:00", pattern=r"^([01][0-9]|2[0-3]):[0-5][0-9]$")
    schoolEnd: str = Field(default="15:00", pattern=r"^([01][0-9]|2[0-3]):[0-5][0-9]$")
    weekdays: list[int] = Field(default_factory=lambda: [1, 2, 3, 4, 5, 6])

    @field_validator("weekdays")
    @classmethod
    def validate_weekdays(cls, value: list[int]) -> list[int]:
        if not value or any(day < 1 or day > 7 for day in value):
            raise ValueError("Weekdays must contain values from 1 to 7")
        if len(set(value)) != len(value):
            raise ValueError("Weekdays must be unique")
        return sorted(value)


class ScheduleSlotIn(BaseModel):
    id: str | None = None
    label: str = Field(min_length=1, max_length=100)
    kind: str = Field(pattern="^(instruction|activity|break)$")
    start: str
    end: str
    position: int = Field(ge=0)
    dayOfWeek: int | None = Field(default=None, ge=1, le=7)
    activityId: str | None = None


class TimetableEntryIn(BaseModel):
    id: str | None = None
    dayOfWeek: int = Field(ge=1, le=7)
    slotId: str
    sectionId: str
    subjectId: str
    teacherId: str | None = None
    room: str | None = Field(default=None, max_length=30)
    locked: bool = False


class TimetablePeriodOut(BaseModel):
    periodNo: int
    slotId: str
    start: str
    end: str
    kind: str


class TimetableDayOut(BaseModel):
    day: int
    isWorking: bool
    halfDay: bool = False


class TimetableCellOut(BaseModel):
    day: int
    periodNo: int
    slotId: str
    sectionId: str = ""
    subjectId: str | None = None
    subjectName: str = ""
    teacherId: str | None = None
    teacherName: str = ""
    room: str | None = None
    locked: bool = False
    status: str
    clashReason: str | None = None
    cellSource: str | None = None


class TimetableSchoolCellPatch(BaseModel):
    dayOfWeek: int = Field(ge=1, le=7)
    slotId: str
    subjectId: str | None = None
    teacherId: str | None = None
    room: str | None = Field(default=None, max_length=30)
    clear: bool = False


class TimetableApplySchoolDefaultsIn(BaseModel):
    mode: str = Field(pattern="^(fill_empty|override_all)$")


class TimetableOut(BaseModel):
    view: str
    itemId: str | None = None
    state: str
    periods: list[TimetablePeriodOut]
    days: list[TimetableDayOut]
    cells: list[TimetableCellOut]
    draftSavedAt: datetime | None = None
    publishedAt: datetime | None = None
    changedSincePublish: bool = False


class TimetableCellPatch(BaseModel):
    sectionId: str
    dayOfWeek: int = Field(ge=1, le=7)
    slotId: str
    subjectId: str | None = None
    teacherId: str | None = None
    room: str | None = Field(default=None, max_length=30)
    locked: bool | None = None
    clear: bool = False


class TimetableClashOut(BaseModel):
    clashId: str
    type: str
    day: int
    periodNo: int
    sectionIds: list[str]
    teacherId: str | None = None
    room: str | None = None
    message: str


class TimetableClashesOut(BaseModel):
    items: list[TimetableClashOut]


class TimetablePeriodLimitWarningOut(BaseModel):
    warningId: str
    sectionIds: list[str]
    subjectId: str | None = None
    scheduledCount: int
    allowedCount: int
    message: str


class TimetablePeriodLimitWarningsOut(BaseModel):
    items: list[TimetablePeriodLimitWarningOut]


class TimetableTeacherLoadItemOut(BaseModel):
    teacherId: str
    name: str = ""
    subject: str
    periodsUsed: int
    periodsNeeded: int | None = None


class TimetableTeacherLoadOut(BaseModel):
    items: list[TimetableTeacherLoadItemOut]


class TimetablePublishOut(BaseModel):
    publishedAt: datetime
    cellCount: int
    changedSincePublish: bool = False


class TimetableAutoFillProposal(BaseModel):
    sectionId: str
    dayOfWeek: int = Field(ge=1, le=7)
    slotId: str
    periodNo: int | None = None
    subjectId: str
    subjectName: str = ""
    teacherId: str | None = None
    selected: bool = True


class TimetableAutoFillIn(BaseModel):
    accept: bool = False
    sectionIds: list[str] = Field(default_factory=list)
    campusId: str | None = None
    proposed: list[TimetableAutoFillProposal] = Field(default_factory=list)


class TimetableAutoFillOut(BaseModel):
    proposedCount: int = 0
    needsDecisionCount: int = 0
    proposed: list[TimetableAutoFillProposal] = Field(default_factory=list)
    couldNotFill: list[dict] = Field(default_factory=list)
    appliedCount: int | None = None


class TimetableSubstitutionPeriodOut(BaseModel):
    sectionId: str
    slotId: str
    periodNo: int
    substituteTeacherId: str | None = None
    substitutionId: str | None = None


class TimetableSubstitutionItemOut(BaseModel):
    teacherId: str
    note: str = ""
    periods: list[TimetableSubstitutionPeriodOut] = Field(default_factory=list)


class TimetableSubstitutionsOut(BaseModel):
    date: date
    items: list[TimetableSubstitutionItemOut] = Field(default_factory=list)
    savedCount: int | None = None


class TimetableSubstitutionSaveIn(BaseModel):
    date: date
    substitutions: list[dict] = Field(min_length=1)


class SpecialDayListItemOut(BaseModel):
    specialDayId: str
    date: date
    name: str
    sections: list[str] = Field(default_factory=list)
    teacherIds: list[str] = Field(default_factory=list)
    replacesRegularSchedule: bool = True


class SpecialDayListOut(BaseModel):
    items: list[SpecialDayListItemOut] = Field(default_factory=list)


class InstituteRoleSettingsOut(BaseModel):
    principalCanEditTimetable: bool = True


class InstituteRoleSettingsUpdate(BaseModel):
    principalCanEditTimetable: bool | None = None


class SpecialDayActivityIn(BaseModel):
    activityId: str
    start: str
    end: str
    position: int = Field(ge=0)
    sectionIds: list[str] = Field(min_length=1)
    teacherIds: list[str] = Field(min_length=1)

    @field_validator("sectionIds", "teacherIds")
    @classmethod
    def require_unique_ids(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("Special activity IDs must be unique")
        return value


class SpecialDayIn(BaseModel):
    date: date
    label: str = Field(min_length=1, max_length=100)
    replaceRegular: bool = True
    activities: list[SpecialDayActivityIn] = Field(min_length=1)

    @field_validator("label")
    @classmethod
    def require_label(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Special day label is required")
        return value


class ScheduleUpdate(BaseModel):
    revision: int
    settings: ScheduleSettingsIn
    slots: list[ScheduleSlotIn]
    entries: list[TimetableEntryIn]
    specialDays: list[SpecialDayIn] | None = None


class TeacherAbsenceCreate(BaseModel):
    teacherId: str
    absenceDate: date
    substituteTeacherId: str | None = None
    note: str = Field(default="", max_length=500)


class TeacherAbsenceOut(BaseModel):
    id: str
    teacherId: str
    absenceDate: date
    substituteTeacherId: str | None = None
    note: str


class SectionEnrollmentOut(BaseModel):
    sectionId: str
    sectionName: str
    className: str
    branchName: str | None = None
    memberType: str | None = None


class SectionOverviewAssignment(BaseModel):
    id: str
    title: str
    description: str
    assignmentType: str
    dueDate: str | None
    submittedCount: int
    enrolledStudents: int
    completionPercent: int


class SectionOverviewOut(BaseModel):
    sectionId: str
    sectionName: str
    className: str
    teacherCount: int
    studentCount: int
    notesCount: int
    averageCompletionPercent: int | None
    assignments: list[SectionOverviewAssignment]
    students: list[dict] | None = None
    teachers: list[dict] | None = None


class SectionClassDashboardOut(BaseModel):
    absenceAlertDays: int
    todayAttendance: dict
    prolongedAbsence: list[dict]
    upcomingExams: list[dict]
    notices: list[dict]
    awards: list[dict]
    events: list[dict]


class NoteCreate(BaseModel):
    content: str


class NoteOut(BaseModel):
    id: str
    content: str
    noteDate: date
    teacherId: str


class InstitutePostCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    body: str = Field(min_length=1, max_length=5000)
    audience: str = Field(
        default="everyone",
        pattern="^(everyone|staff|students|parents|class|boys|girls|teachers|principals|custom|distribution_list)$",
    )
    targetSectionIds: list[str] = Field(default_factory=list)
    targetUserIds: list[str] = Field(default_factory=list)
    studentGender: str | None = None
    distributionListId: str | None = None


class InstitutePostOut(BaseModel):
    id: str
    title: str
    body: str
    postedBy: str
    audience: str = "everyone"
    targetSectionIds: list[str] = Field(default_factory=list)
    targetUserIds: list[str] = Field(default_factory=list)
    studentGender: str | None = None
    distributionListId: str | None = None
    createdAt: datetime


class DistributionListCreate(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    audience: str = Field(
        default="everyone",
        pattern="^(everyone|staff|students|parents|class|boys|girls|teachers|principals|custom)$",
    )
    targetSectionIds: list[str] = Field(default_factory=list)
    targetUserIds: list[str] = Field(default_factory=list)
    studentGender: str | None = None


class DistributionListOut(BaseModel):
    id: str
    name: str
    audience: str
    targetSectionIds: list[str] = Field(default_factory=list)
    targetUserIds: list[str] = Field(default_factory=list)
    studentGender: str | None = None
    createdAt: datetime


class CalendarEventCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    description: str = ""
    eventDate: date
    branchId: str | None = None
    audience: str = Field(
        default="everyone",
        pattern="^(everyone|staff|students|parents|class|boys|girls|teachers|principals|custom|distribution_list)$",
    )
    targetSectionIds: list[str] = Field(default_factory=list)
    targetUserIds: list[str] = Field(default_factory=list)
    studentGender: str | None = None
    distributionListId: str | None = None


class CalendarEventOut(BaseModel):
    id: str
    title: str
    description: str
    eventDate: date
    branchId: str | None
    audience: str = "everyone"
    targetSectionIds: list[str] = Field(default_factory=list)
    targetUserIds: list[str] = Field(default_factory=list)
    studentGender: str | None = None
    distributionListId: str | None = None
    createdBy: str
    createdAt: datetime


class ExamCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    academicYearId: str | None = None
    sectionId: str | None = None
    subjectId: str | None = None
    maxMarks: int = Field(default=100, ge=1)
    scheduledAt: date | None = None


class ExamUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    sectionId: str | None = None
    subjectId: str | None = None
    maxMarks: int | None = Field(default=None, ge=1)
    scheduledAt: date | None = None


class ExamOut(BaseModel):
    id: str
    instituteId: str
    academicYearId: str | None
    sectionId: str | None
    subjectId: str | None
    name: str
    maxMarks: int
    scheduledAt: date | None
    status: str
    createdBy: str
    createdAt: datetime


class MarkEntryIn(BaseModel):
    studentId: str
    subjectId: str | None = None
    marksObtained: int | None = None
    remarks: str = ""


class MarksUpsert(BaseModel):
    entries: list[MarkEntryIn]


class MarkEntryOut(BaseModel):
    id: str
    examId: str
    studentId: str
    subjectId: str | None
    marksObtained: int | None
    remarks: str


class FeeStructureCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    amountPaise: int = Field(ge=1)
    academicYearId: str | None = None


class FeeStructureOut(BaseModel):
    id: str
    instituteId: str
    academicYearId: str | None
    name: str
    amountPaise: int


class StudentFeeAssign(BaseModel):
    studentId: str
    feeStructureId: str
    amountPaise: int | None = None


class StudentFeeDueOut(BaseModel):
    studentId: str
    feeStructureId: str
    amountPaise: int
    paidPaise: int
    balancePaise: int


class PaymentCreate(BaseModel):
    studentId: str
    amountPaise: int = Field(ge=1)
    method: str = Field(default="cash", pattern="^(cash|upi|bank)$")
    reference: str = ""


class PaymentOut(BaseModel):
    id: str
    instituteId: str
    studentId: str
    amountPaise: int
    method: str
    reference: str
    receiptNumber: str
    recordedBy: str
    createdAt: datetime


class AttendanceSummaryOut(BaseModel):
    studentsTotal: int
    present: int
    absent: int
    late: int
    staffTotal: int
    staffPresent: int
    sectionsTotal: int
    sectionsPending: int


class AssignmentCreate(BaseModel):
    title: str
    description: str = ""
    assignmentType: str = Field(default="assignment", pattern="^(assignment|test)$")
    dueDate: date | None = None


class AssignmentOut(BaseModel):
    id: str
    title: str
    description: str
    assignmentType: str
    dueDate: date | None


class AttendanceRecordIn(BaseModel):
    studentId: str
    status: str = Field(pattern="^(present|absent|late|excused)$")


class AttendanceUpdate(BaseModel):
    attendanceDate: date
    records: list[AttendanceRecordIn]


class AttendancePresentSyncIn(BaseModel):
    attendanceDate: date
    presentStudentIds: list[str] = Field(default_factory=list)
    excusedStudentIds: list[str] = Field(default_factory=list)
    publishState: str = Field(default="submitted", pattern="^(draft|submitted)$")


class AttendanceTotalsOut(BaseModel):
    present: int = 0
    absent: int = 0
    late: int = 0
    excused: int = 0
    unmarked: int = 0


class AttendanceSheetOut(BaseModel):
    startDate: str
    endDate: str
    dates: list[str]
    students: list[dict]
    statusByStudent: dict[str, dict[str, str]]
    totalsByStudent: dict[str, AttendanceTotalsOut] = Field(default_factory=dict)
    totalsLabel: str = "Academic year"
    totalsStartDate: str | None = None
    totalsEndDate: str | None = None
    canEditPastAttendance: bool = False
    canTakeAttendanceToday: bool = False
    publishStateByDate: dict[str, str] = Field(default_factory=dict)


class StudentLeaveRequestOut(BaseModel):
    id: str
    studentId: str
    studentName: str | None = None
    startDate: str
    endDate: str
    reason: str
    status: str
    createdAt: str | None = None


class AttendanceOut(BaseModel):
    studentId: str
    attendanceDate: date
    status: str
    markedBy: str


class SubmissionCreate(BaseModel):
    content: str


class SubmissionOut(BaseModel):
    id: str
    content: str
    studentId: str


class GuardianChildOut(BaseModel):
    studentId: str
    instituteIds: list[str]


class GuardianChildrenOut(BaseModel):
    children: list[GuardianChildOut]


class GuardianLinkSeedItem(BaseModel):
    guardianUserId: str
    studentUserIds: list[str]


class GuardianLinksSeedIn(BaseModel):
    links: list[GuardianLinkSeedItem]


class GuardianLinksSeedOut(BaseModel):
    guardiansUpdated: int


class ParentThreadCreate(BaseModel):
    subject: str = Field(min_length=1, max_length=200)
    initialMessage: str | None = None


class ParentThreadOut(BaseModel):
    id: str
    instituteId: str
    studentId: str
    subject: str
    status: str
    createdByUserId: str
    createdAt: datetime


class ParentMessageCreate(BaseModel):
    body: str = Field(min_length=1)


class ParentMessageOut(BaseModel):
    id: str
    threadId: str
    senderUserId: str
    body: str
    sentAt: datetime


class AssignmentWorkCreate(BaseModel):
    title: str = "Untitled assignment"
    description: str = ""
    assignmentType: str = Field(default="assignment", pattern="^(assignment|test)$")
    audienceType: str = Field(default="section", pattern="^(section|students)$")
    instructions: str = ""


class AssignmentWorkPatch(BaseModel):
    title: str | None = None
    description: str | None = None
    instructions: str | None = None
    audienceType: str | None = Field(default=None, pattern="^(section|students)$")
    audienceStudentIds: list[str] | None = None
    dueAt: str | None = None
    publishAt: str | None = None


class AssignmentWorkPublishIn(BaseModel):
    publishAt: str | None = None


class AssignmentQuestionOptionIn(BaseModel):
    key: str
    label: str
    isCorrect: bool = False


class AssignmentQuestionVariantIn(BaseModel):
    stem: str = ""
    metadata: dict = Field(default_factory=dict)
    options: list[AssignmentQuestionOptionIn] = Field(default_factory=list)


class AssignmentQuestionIn(BaseModel):
    type: str
    sortOrder: int = 0
    points: float = 1
    required: bool = True
    variants: list[AssignmentQuestionVariantIn] = Field(default_factory=list)


class AssignmentQuestionsReplaceIn(BaseModel):
    questions: list[AssignmentQuestionIn]


class AssignmentResponsesPatchIn(BaseModel):
    answers: dict[str, Any] = Field(default_factory=dict)


class AssignmentGradeResponseIn(BaseModel):
    questionId: str
    teacherScore: float | None = None
    feedback: str = ""


class AssignmentGradeIn(BaseModel):
    responses: list[AssignmentGradeResponseIn] = Field(default_factory=list)
    scoresVisible: bool = False
