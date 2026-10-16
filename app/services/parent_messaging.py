from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import ParentTeacherMessage, ParentTeacherThread
from app.roles import PARENT_ROLE
from app.services.guardians import is_guardian_of_student, student_enrolled_in_institute
from app.services.institutes import require_membership


def _require_parent_access(
    db: Session,
    institute_id: str,
    guardian_user_id: str,
    student_id: str,
    bearer_token: str,
) -> None:
    member = require_membership(db, institute_id, guardian_user_id)
    if member.role != PARENT_ROLE:
        raise PermissionError("Parent role required")
    if not student_enrolled_in_institute(db, institute_id, student_id):
        raise PermissionError("Student is not enrolled in this institute")
    if not is_guardian_of_student(db, guardian_user_id, student_id, bearer_token):
        raise PermissionError("Not linked as guardian for this student")


def list_threads(
    db: Session,
    institute_id: str,
    guardian_user_id: str,
    student_id: str,
    bearer_token: str,
) -> list[dict]:
    _require_parent_access(db, institute_id, guardian_user_id, student_id, bearer_token)
    rows = db.scalars(
        select(ParentTeacherThread)
        .where(
            ParentTeacherThread.institute_id == institute_id,
            ParentTeacherThread.student_id == student_id,
        )
        .order_by(ParentTeacherThread.created_at.desc())
    ).all()
    return [thread_to_dict(row) for row in rows]


def create_thread(
    db: Session,
    institute_id: str,
    guardian_user_id: str,
    student_id: str,
    bearer_token: str,
    *,
    subject: str,
    initial_message: str | None = None,
) -> dict:
    _require_parent_access(db, institute_id, guardian_user_id, student_id, bearer_token)
    thread = ParentTeacherThread(
        institute_id=institute_id,
        student_id=student_id,
        subject=subject.strip(),
        created_by_user_id=guardian_user_id,
    )
    db.add(thread)
    db.flush()
    if initial_message and initial_message.strip():
        db.add(
            ParentTeacherMessage(
                thread_id=thread.id,
                sender_user_id=guardian_user_id,
                body=initial_message.strip(),
            )
        )
    db.commit()
    db.refresh(thread)
    return thread_to_dict(thread)


def post_message(
    db: Session,
    institute_id: str,
    guardian_user_id: str,
    student_id: str,
    thread_id: str,
    bearer_token: str,
    *,
    body: str,
) -> dict:
    _require_parent_access(db, institute_id, guardian_user_id, student_id, bearer_token)
    thread = db.get(ParentTeacherThread, thread_id)
    if not thread or thread.institute_id != institute_id or thread.student_id != student_id:
        raise PermissionError("Thread not found")
    if thread.status != "open":
        raise PermissionError("Thread is closed")
    message = ParentTeacherMessage(
        thread_id=thread.id,
        sender_user_id=guardian_user_id,
        body=body.strip(),
    )
    db.add(message)
    db.commit()
    db.refresh(message)
    return message_to_dict(message)


def thread_to_dict(thread: ParentTeacherThread) -> dict:
    return {
        "id": thread.id,
        "instituteId": thread.institute_id,
        "studentId": thread.student_id,
        "subject": thread.subject,
        "status": thread.status,
        "createdByUserId": thread.created_by_user_id,
        "createdAt": thread.created_at,
    }


def message_to_dict(message: ParentTeacherMessage) -> dict:
    return {
        "id": message.id,
        "threadId": message.thread_id,
        "senderUserId": message.sender_user_id,
        "body": message.body,
        "sentAt": message.sent_at,
    }
