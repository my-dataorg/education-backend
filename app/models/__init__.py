import secrets
import uuid
from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Institute(Base):
    __tablename__ = "institutes"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name: Mapped[str] = mapped_column(String(200))
    join_code: Mapped[str] = mapped_column(String(12), unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Branch(Base):
    __tablename__ = "branches"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    institute_id: Mapped[str] = mapped_column(String(36), ForeignKey("institutes.id"))
    name: Mapped[str] = mapped_column(String(200))
    address: Mapped[str] = mapped_column(String(500), default="")
    city: Mapped[str] = mapped_column(String(100), default="")
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False)


class InstituteMember(Base):
    __tablename__ = "institute_members"
    __table_args__ = (UniqueConstraint("institute_id", "user_id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    institute_id: Mapped[str] = mapped_column(String(36), ForeignKey("institutes.id"))
    user_id: Mapped[str] = mapped_column(String(64))
    role: Mapped[str] = mapped_column(String(32))


class InstituteInvitation(Base):
    __tablename__ = "institute_invitations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    institute_id: Mapped[str] = mapped_column(String(36), ForeignKey("institutes.id"))
    invitee_user_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    invitee_email: Mapped[str] = mapped_column(String(200), default="")
    role: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(16), default="pending")  # pending, accepted, rejected
    invited_by: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    responded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class InstituteJoinRequest(Base):
    __tablename__ = "institute_join_requests"
    __table_args__ = (UniqueConstraint("institute_id", "user_id", "status"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    institute_id: Mapped[str] = mapped_column(String(36), ForeignKey("institutes.id"))
    user_id: Mapped[str] = mapped_column(String(64))
    requested_role: Mapped[str] = mapped_column(String(32))
    message: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(16), default="pending")  # pending, accepted, rejected
    reviewed_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    responded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Class(Base):
    __tablename__ = "classes"
    __table_args__ = (UniqueConstraint("institute_id", "name"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    institute_id: Mapped[str] = mapped_column(String(36), ForeignKey("institutes.id"))
    name: Mapped[str] = mapped_column(String(200))
    grade_band: Mapped[str] = mapped_column(String(16), default="primary")


class Section(Base):
    __tablename__ = "sections"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    institute_id: Mapped[str] = mapped_column(String(36), ForeignKey("institutes.id"))
    class_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("classes.id"), nullable=True)
    branch_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("branches.id"), nullable=True)
    name: Mapped[str] = mapped_column(String(200))
    class_name: Mapped[str] = mapped_column(String(200), default="")
    grade_band: Mapped[str] = mapped_column(String(16), default="primary")


class Subject(Base):
    __tablename__ = "subjects"
    __table_args__ = (UniqueConstraint("institute_id", "name"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    institute_id: Mapped[str] = mapped_column(String(36), ForeignKey("institutes.id"))
    name: Mapped[str] = mapped_column(String(120))


class TeacherSubject(Base):
    __tablename__ = "teacher_subjects"
    __table_args__ = (UniqueConstraint("institute_id", "user_id", "subject_id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    institute_id: Mapped[str] = mapped_column(String(36), ForeignKey("institutes.id"))
    user_id: Mapped[str] = mapped_column(String(64))
    subject_id: Mapped[str] = mapped_column(String(36), ForeignKey("subjects.id"))


class TeacherGradeBand(Base):
    __tablename__ = "teacher_grade_bands"
    __table_args__ = (UniqueConstraint("institute_id", "user_id", "grade_band"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    institute_id: Mapped[str] = mapped_column(String(36), ForeignKey("institutes.id"))
    user_id: Mapped[str] = mapped_column(String(64))
    grade_band: Mapped[str] = mapped_column(String(16))


class Period(Base):
    __tablename__ = "periods"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    institute_id: Mapped[str] = mapped_column(String(36), ForeignKey("institutes.id"))
    section_id: Mapped[str] = mapped_column(String(36), ForeignKey("sections.id"))
    subject_id: Mapped[str] = mapped_column(String(36), ForeignKey("subjects.id"))
    teacher_user_id: Mapped[str] = mapped_column(String(64))
    semester: Mapped[str] = mapped_column(String(80))
    weekday: Mapped[str] = mapped_column(String(80))
    start_time: Mapped[str] = mapped_column(String(5))
    duration_minutes: Mapped[int] = mapped_column(Integer, default=60)


class SectionMember(Base):
    __tablename__ = "section_members"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    section_id: Mapped[str] = mapped_column(String(36), ForeignKey("sections.id"))
    user_id: Mapped[str] = mapped_column(String(64))
    member_type: Mapped[str] = mapped_column(String(16))  # teacher, student
    subject_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("subjects.id"), nullable=True)


class DailyNote(Base):
    __tablename__ = "daily_notes"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    section_id: Mapped[str] = mapped_column(String(36), ForeignKey("sections.id"))
    teacher_id: Mapped[str] = mapped_column(String(64))
    subject_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("subjects.id"), nullable=True)
    content: Mapped[str] = mapped_column(Text)
    note_date: Mapped[date] = mapped_column(Date, server_default=func.current_date())


class Assignment(Base):
    __tablename__ = "assignments"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    section_id: Mapped[str] = mapped_column(String(36), ForeignKey("sections.id"))
    subject_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("subjects.id"), nullable=True)
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    created_by: Mapped[str] = mapped_column(String(64))


class Submission(Base):
    __tablename__ = "submissions"
    __table_args__ = (UniqueConstraint("assignment_id", "student_id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    assignment_id: Mapped[str] = mapped_column(String(36), ForeignKey("assignments.id"))
    student_id: Mapped[str] = mapped_column(String(64))
    content: Mapped[str] = mapped_column(Text)
    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


def new_join_code() -> str:
    return secrets.token_urlsafe(6)[:8].upper()
