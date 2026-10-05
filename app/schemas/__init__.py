from datetime import date, datetime

from pydantic import BaseModel, Field, field_validator


class InstituteCreate(BaseModel):
    name: str = Field(min_length=2, max_length=200)


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


class MemberAdd(BaseModel):
    userId: str
    role: str = Field(pattern="^(admin|principal|teacher|lecturer|professor|student)$")


class MemberRoleUpdate(BaseModel):
    role: str = Field(pattern="^(admin|principal|teacher|lecturer|professor|student)$")


class MemberProfileOut(BaseModel):
    userId: str
    role: str
    sections: list[dict]
    branches: list[str]


class BranchTeacherBrief(BaseModel):
    userId: str
    role: str
    firstName: str = ""
    lastName: str = ""
    displayName: str = ""
    email: str = ""
    username: str = ""


class BranchStudentBrief(BaseModel):
    userId: str
    role: str
    firstName: str = ""
    lastName: str = ""
    displayName: str = ""
    email: str = ""
    username: str = ""


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


class InvitationCreate(BaseModel):
    userId: str
    role: str = Field(pattern="^(teacher|student)$")


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
    requestedRole: str = Field(pattern="^(teacher|lecturer|professor|student)$")
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


class BranchCreate(BaseModel):
    name: str = Field(min_length=2, max_length=200)
    address: str = ""
    city: str = ""
    isPrimary: bool = False


class BranchUpdate(BaseModel):
    name: str | None = None
    address: str | None = None
    city: str | None = None
    isPrimary: bool | None = None


class BranchOut(BaseModel):
    id: str
    name: str
    address: str
    city: str
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


class SectionSubjectAssign(BaseModel):
    subjectId: str


class TeacherSubjectAssign(BaseModel):
    userId: str


class TeacherSubjectOut(BaseModel):
    userId: str


class SectionSubjectOut(BaseModel):
    id: str
    name: str
    teachers: list[TeacherSubjectOut] = Field(default_factory=list)


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


class ScheduleOut(BaseModel):
    instituteId: str
    revision: int
    settings: ScheduleSettingsOut
    slots: list[ScheduleSlotOut]
    entries: list[TimetableEntryOut]


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


class ScheduleUpdate(BaseModel):
    revision: int
    settings: ScheduleSettingsIn
    slots: list[ScheduleSlotIn]
    entries: list[TimetableEntryIn]


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


class NoteCreate(BaseModel):
    content: str


class NoteOut(BaseModel):
    id: str
    content: str
    noteDate: date
    teacherId: str


class AssignmentCreate(BaseModel):
    title: str
    description: str = ""
    dueDate: date | None = None


class AssignmentOut(BaseModel):
    id: str
    title: str
    description: str
    dueDate: date | None


class SubmissionCreate(BaseModel):
    content: str


class SubmissionOut(BaseModel):
    id: str
    content: str
    studentId: str
