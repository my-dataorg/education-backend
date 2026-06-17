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


class BranchSummaryOut(BaseModel):
    id: str
    name: str
    isPrimary: bool
    address: str
    city: str
    teacherCount: int
    studentCount: int
    teachers: list[BranchTeacherBrief]


class UpcomingEventOut(BaseModel):
    type: str
    title: str
    dueDate: str
    sectionName: str
    branchName: str | None = None


class InstituteSummaryOut(BaseModel):
    branchCount: int
    branches: list[BranchSummaryOut]
    upcomingEvents: list[UpcomingEventOut]


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
    role: str
    status: str
    invitedBy: str
    createdAt: datetime


class InvitationRespondOut(BaseModel):
    instituteId: str
    role: str


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
