from datetime import date, datetime

from pydantic import BaseModel, Field, model_validator


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
    email: str | None = None
    userId: str | None = None
    role: str = Field(pattern="^(admin|principal|teacher|lecturer|professor|student)$")

    @model_validator(mode="after")
    def require_invitee(self) -> "InvitationCreate":
        if not self.email and not self.userId:
            raise ValueError("Email or userId is required")
        return self


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
