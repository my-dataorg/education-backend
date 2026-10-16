import secrets
import uuid
from datetime import date, datetime, time

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, String, Text, Time, UniqueConstraint, func
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


class AcademicYear(Base):
    __tablename__ = "academic_years"
    __table_args__ = (UniqueConstraint("institute_id", "label"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    institute_id: Mapped[str] = mapped_column(String(36), ForeignKey("institutes.id"))
    label: Mapped[str] = mapped_column(String(32))
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date] = mapped_column(Date)
    board: Mapped[str] = mapped_column(String(32), default="CBSE")
    term_count: Mapped[int] = mapped_column(default=2)
    grading_scale: Mapped[str] = mapped_column(String(64), default="Marks + grade (A1–E)")
    medium: Mapped[str] = mapped_column(String(64), default="English")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class AcademicTerm(Base):
    __tablename__ = "academic_terms"
    __table_args__ = (UniqueConstraint("academic_year_id", "name"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    academic_year_id: Mapped[str] = mapped_column(String(36), ForeignKey("academic_years.id"))
    name: Mapped[str] = mapped_column(String(64))
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date] = mapped_column(Date)
    weight_percent: Mapped[int] = mapped_column(default=50)


class InstituteMember(Base):
    __tablename__ = "institute_members"
    __table_args__ = (UniqueConstraint("institute_id", "user_id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    institute_id: Mapped[str] = mapped_column(String(36), ForeignKey("institutes.id"))
    user_id: Mapped[str] = mapped_column(String(64))
    role: Mapped[str] = mapped_column(String(32))


class InstitutePost(Base):
    __tablename__ = "institute_posts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    institute_id: Mapped[str] = mapped_column(String(36), ForeignKey("institutes.id"))
    title: Mapped[str] = mapped_column(String(200))
    body: Mapped[str] = mapped_column(Text)
    posted_by: Mapped[str] = mapped_column(String(64))
    audience: Mapped[str] = mapped_column(String(32), default="everyone")
    target_section_ids: Mapped[str] = mapped_column(Text, default="")
    target_user_ids: Mapped[str] = mapped_column(Text, default="")
    student_gender: Mapped[str | None] = mapped_column(String(16), nullable=True)
    distribution_list_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class NoticeDistributionList(Base):
    __tablename__ = "notice_distribution_lists"
    __table_args__ = (UniqueConstraint("institute_id", "name"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    institute_id: Mapped[str] = mapped_column(String(36), ForeignKey("institutes.id"))
    name: Mapped[str] = mapped_column(String(120))
    audience: Mapped[str] = mapped_column(String(32), default="everyone")
    target_section_ids: Mapped[str] = mapped_column(Text, default="")
    target_user_ids: Mapped[str] = mapped_column(Text, default="")
    student_gender: Mapped[str | None] = mapped_column(String(16), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class InstituteCalendarEvent(Base):
    __tablename__ = "institute_calendar_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    institute_id: Mapped[str] = mapped_column(String(36), ForeignKey("institutes.id"))
    branch_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("branches.id"), nullable=True)
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    event_date: Mapped[date] = mapped_column(Date)
    audience: Mapped[str] = mapped_column(String(32), default="everyone")
    target_section_ids: Mapped[str] = mapped_column(Text, default="")
    target_user_ids: Mapped[str] = mapped_column(Text, default="")
    student_gender: Mapped[str | None] = mapped_column(String(16), nullable=True)
    distribution_list_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_by: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Exam(Base):
    __tablename__ = "exams"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    institute_id: Mapped[str] = mapped_column(String(36), ForeignKey("institutes.id"))
    academic_year_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("academic_years.id"), nullable=True)
    section_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("sections.id"), nullable=True)
    subject_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("subjects.id"), nullable=True)
    name: Mapped[str] = mapped_column(String(200))
    max_marks: Mapped[int] = mapped_column(Integer, default=100)
    scheduled_at: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="draft")
    created_by: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class MarkEntry(Base):
    __tablename__ = "mark_entries"
    __table_args__ = (UniqueConstraint("exam_id", "student_id", "subject_id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    exam_id: Mapped[str] = mapped_column(String(36), ForeignKey("exams.id"))
    student_id: Mapped[str] = mapped_column(String(64))
    subject_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("subjects.id"), nullable=True)
    marks_obtained: Mapped[int | None] = mapped_column(Integer, nullable=True)
    remarks: Mapped[str] = mapped_column(String(500), default="")


class FeeStructure(Base):
    __tablename__ = "fee_structures"
    __table_args__ = (UniqueConstraint("institute_id", "academic_year_id", "name"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    institute_id: Mapped[str] = mapped_column(String(36), ForeignKey("institutes.id"))
    academic_year_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("academic_years.id"), nullable=True)
    name: Mapped[str] = mapped_column(String(200))
    amount_paise: Mapped[int] = mapped_column(Integer)


class StudentFee(Base):
    __tablename__ = "student_fees"
    __table_args__ = (UniqueConstraint("institute_id", "student_id", "fee_structure_id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    institute_id: Mapped[str] = mapped_column(String(36), ForeignKey("institutes.id"))
    student_id: Mapped[str] = mapped_column(String(64))
    fee_structure_id: Mapped[str] = mapped_column(String(36), ForeignKey("fee_structures.id"))
    amount_paise: Mapped[int] = mapped_column(Integer)
    paid_paise: Mapped[int] = mapped_column(Integer, default=0)


class Payment(Base):
    __tablename__ = "payments"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    institute_id: Mapped[str] = mapped_column(String(36), ForeignKey("institutes.id"))
    student_id: Mapped[str] = mapped_column(String(64))
    amount_paise: Mapped[int] = mapped_column(Integer)
    method: Mapped[str] = mapped_column(String(32), default="cash")
    reference: Mapped[str] = mapped_column(String(200), default="")
    receipt_number: Mapped[str] = mapped_column(String(64))
    recorded_by: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class InstituteInvitation(Base):
    __tablename__ = "institute_invitations"
    __table_args__ = (UniqueConstraint("institute_id", "invitee_user_id", "status"),)

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


class Section(Base):
    __tablename__ = "sections"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    institute_id: Mapped[str] = mapped_column(String(36), ForeignKey("institutes.id"))
    branch_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("branches.id"), nullable=True)
    name: Mapped[str] = mapped_column(String(200))
    class_name: Mapped[str] = mapped_column(String(200), default="")


class SectionMember(Base):
    __tablename__ = "section_members"
    __table_args__ = (UniqueConstraint("section_id", "user_id", "member_type"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    section_id: Mapped[str] = mapped_column(String(36), ForeignKey("sections.id"))
    user_id: Mapped[str] = mapped_column(String(64))
    member_type: Mapped[str] = mapped_column(String(16))  # teacher, student


class Subject(Base):
    __tablename__ = "subjects"
    __table_args__ = (UniqueConstraint("institute_id", "name"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    institute_id: Mapped[str] = mapped_column(String(36), ForeignKey("institutes.id"))
    name: Mapped[str] = mapped_column(String(200))


class Activity(Base):
    __tablename__ = "activities"
    __table_args__ = (UniqueConstraint("institute_id", "name"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    institute_id: Mapped[str] = mapped_column(String(36), ForeignKey("institutes.id"))
    name: Mapped[str] = mapped_column(String(100))
    is_system: Mapped[bool] = mapped_column(Boolean, default=False)


class SectionSubject(Base):
    __tablename__ = "section_subjects"
    __table_args__ = (UniqueConstraint("section_id", "subject_id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    section_id: Mapped[str] = mapped_column(String(36), ForeignKey("sections.id"))
    subject_id: Mapped[str] = mapped_column(String(36), ForeignKey("subjects.id"))
    weekly_periods: Mapped[int | None] = mapped_column(Integer, nullable=True)


class TeacherSubjectAssignment(Base):
    __tablename__ = "teacher_subject_assignments"
    __table_args__ = (UniqueConstraint("section_id", "subject_id", "teacher_id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    section_id: Mapped[str] = mapped_column(String(36), ForeignKey("sections.id"))
    subject_id: Mapped[str] = mapped_column(String(36), ForeignKey("subjects.id"))
    teacher_id: Mapped[str] = mapped_column(String(64))


class SectionSubjectStudentAssignment(Base):
    __tablename__ = "section_subject_student_assignments"
    __table_args__ = (UniqueConstraint("section_id", "subject_id", "student_id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    section_id: Mapped[str] = mapped_column(String(36), ForeignKey("sections.id"))
    subject_id: Mapped[str] = mapped_column(String(36), ForeignKey("subjects.id"))
    student_id: Mapped[str] = mapped_column(String(64))


class ScheduleSettings(Base):
    __tablename__ = "schedule_settings"

    institute_id: Mapped[str] = mapped_column(String(36), ForeignKey("institutes.id"), primary_key=True)
    timezone: Mapped[str] = mapped_column(String(64), default="Asia/Kolkata")
    school_start: Mapped[time] = mapped_column(Time, default=time(8, 0))
    school_end: Mapped[time] = mapped_column(Time, default=time(15, 0))
    weekdays: Mapped[str] = mapped_column(String(32), default="1,2,3,4,5,6")
    revision: Mapped[int] = mapped_column(default=1)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    draft_saved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ScheduleSlot(Base):
    __tablename__ = "schedule_slots"
    __table_args__ = (UniqueConstraint("institute_id", "position"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    institute_id: Mapped[str] = mapped_column(String(36), ForeignKey("institutes.id"))
    label: Mapped[str] = mapped_column(String(100))
    kind: Mapped[str] = mapped_column(String(16), default="instruction")
    start_time: Mapped[time] = mapped_column(Time)
    end_time: Mapped[time] = mapped_column(Time)
    position: Mapped[int] = mapped_column()
    day_of_week: Mapped[int | None] = mapped_column(nullable=True)
    activity_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("activities.id"), nullable=True)


class TimetableEntry(Base):
    __tablename__ = "timetable_entries"
    __table_args__ = (UniqueConstraint("slot_id", "day_of_week", "section_id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    institute_id: Mapped[str] = mapped_column(String(36), ForeignKey("institutes.id"))
    slot_id: Mapped[str] = mapped_column(String(36), ForeignKey("schedule_slots.id"))
    day_of_week: Mapped[int] = mapped_column()
    section_id: Mapped[str] = mapped_column(String(36), ForeignKey("sections.id"))
    subject_id: Mapped[str] = mapped_column(String(36), ForeignKey("subjects.id"))
    teacher_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    room: Mapped[str | None] = mapped_column(String(30), nullable=True)
    locked: Mapped[bool] = mapped_column(Boolean, default=False)


class PublishedTimetableEntry(Base):
    __tablename__ = "published_timetable_entries"
    __table_args__ = (UniqueConstraint("slot_id", "day_of_week", "section_id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    institute_id: Mapped[str] = mapped_column(String(36), ForeignKey("institutes.id"))
    slot_id: Mapped[str] = mapped_column(String(36), ForeignKey("schedule_slots.id"))
    day_of_week: Mapped[int] = mapped_column()
    section_id: Mapped[str] = mapped_column(String(36), ForeignKey("sections.id"))
    subject_id: Mapped[str] = mapped_column(String(36), ForeignKey("subjects.id"))
    teacher_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    room: Mapped[str | None] = mapped_column(String(30), nullable=True)
    locked: Mapped[bool] = mapped_column(Boolean, default=False)


class ScheduleSpecialDay(Base):
    __tablename__ = "schedule_special_days"
    __table_args__ = (UniqueConstraint("institute_id", "special_date"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    institute_id: Mapped[str] = mapped_column(String(36), ForeignKey("institutes.id"))
    special_date: Mapped[date] = mapped_column(Date)
    label: Mapped[str] = mapped_column(String(100))
    replace_regular: Mapped[bool] = mapped_column(Boolean, default=True)


class SpecialDayActivity(Base):
    __tablename__ = "special_day_activities"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    special_day_id: Mapped[str] = mapped_column(String(36), ForeignKey("schedule_special_days.id"))
    activity_id: Mapped[str] = mapped_column(String(36), ForeignKey("activities.id"))
    start_time: Mapped[time] = mapped_column(Time)
    end_time: Mapped[time] = mapped_column(Time)
    position: Mapped[int] = mapped_column()


class SpecialDayActivitySection(Base):
    __tablename__ = "special_day_activity_sections"
    __table_args__ = (UniqueConstraint("special_activity_id", "section_id"),)

    special_activity_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("special_day_activities.id"), primary_key=True
    )
    section_id: Mapped[str] = mapped_column(String(36), ForeignKey("sections.id"), primary_key=True)


class SpecialDayActivityTeacher(Base):
    __tablename__ = "special_day_activity_teachers"
    __table_args__ = (UniqueConstraint("special_activity_id", "teacher_id"),)

    special_activity_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("special_day_activities.id"), primary_key=True
    )
    teacher_id: Mapped[str] = mapped_column(String(64), primary_key=True)


class TeacherAbsence(Base):
    __tablename__ = "teacher_absences"
    __table_args__ = (UniqueConstraint("institute_id", "teacher_id", "absence_date"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    institute_id: Mapped[str] = mapped_column(String(36), ForeignKey("institutes.id"))
    teacher_id: Mapped[str] = mapped_column(String(64))
    absence_date: Mapped[date] = mapped_column(Date)
    substitute_teacher_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    note: Mapped[str] = mapped_column(String(500), default="")


class InstituteRoleSettings(Base):
    __tablename__ = "institute_role_settings"

    institute_id: Mapped[str] = mapped_column(String(36), ForeignKey("institutes.id"), primary_key=True)
    principal_can_edit_timetable: Mapped[bool] = mapped_column(Boolean, default=True)


class TimetableSubstitution(Base):
    __tablename__ = "timetable_substitutions"
    __table_args__ = (
        UniqueConstraint("institute_id", "substitution_date", "slot_id", "section_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    institute_id: Mapped[str] = mapped_column(String(36), ForeignKey("institutes.id"))
    substitution_date: Mapped[date] = mapped_column(Date)
    slot_id: Mapped[str] = mapped_column(String(36), ForeignKey("schedule_slots.id"))
    section_id: Mapped[str] = mapped_column(String(36), ForeignKey("sections.id"))
    original_teacher_id: Mapped[str] = mapped_column(String(64))
    substitute_teacher_id: Mapped[str] = mapped_column(String(64))


class DailyNote(Base):
    __tablename__ = "daily_notes"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    section_id: Mapped[str] = mapped_column(String(36), ForeignKey("sections.id"))
    teacher_id: Mapped[str] = mapped_column(String(64))
    content: Mapped[str] = mapped_column(Text)
    note_date: Mapped[date] = mapped_column(Date, server_default=func.current_date())


class Assignment(Base):
    __tablename__ = "assignments"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    section_id: Mapped[str] = mapped_column(String(36), ForeignKey("sections.id"))
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    assignment_type: Mapped[str] = mapped_column(String(16), default="assignment")
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    created_by: Mapped[str] = mapped_column(String(64))


class AttendanceRecord(Base):
    __tablename__ = "attendance_records"
    __table_args__ = (UniqueConstraint("section_id", "student_id", "attendance_date"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    section_id: Mapped[str] = mapped_column(String(36), ForeignKey("sections.id"))
    student_id: Mapped[str] = mapped_column(String(64))
    attendance_date: Mapped[date] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(16))
    marked_by: Mapped[str] = mapped_column(String(64))


class Submission(Base):
    __tablename__ = "submissions"
    __table_args__ = (UniqueConstraint("assignment_id", "student_id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    assignment_id: Mapped[str] = mapped_column(String(36), ForeignKey("assignments.id"))
    student_id: Mapped[str] = mapped_column(String(64))
    content: Mapped[str] = mapped_column(Text)
    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class GuardianLinkCache(Base):
    """TTL cache of Social guardian→children links (not authoritative)."""

    __tablename__ = "guardian_link_cache"

    guardian_user_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    student_ids_json: Mapped[str] = mapped_column(Text, default="[]")
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ParentTeacherThread(Base):
    __tablename__ = "parent_teacher_threads"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    institute_id: Mapped[str] = mapped_column(String(36), ForeignKey("institutes.id"))
    student_id: Mapped[str] = mapped_column(String(64))
    subject: Mapped[str] = mapped_column(String(200))
    created_by_user_id: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16), default="open")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ParentTeacherMessage(Base):
    __tablename__ = "parent_teacher_messages"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    thread_id: Mapped[str] = mapped_column(String(36), ForeignKey("parent_teacher_threads.id"))
    sender_user_id: Mapped[str] = mapped_column(String(64))
    body: Mapped[str] = mapped_column(Text)
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


def new_join_code() -> str:
    return secrets.token_urlsafe(6)[:8].upper()
