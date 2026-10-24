"""Assignment works: publish lifecycle, questions, attempts, grading."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.models import (
    Assignment,
    AssignmentAttempt,
    AssignmentAudienceStudent,
    AssignmentQuestion,
    AssignmentQuestionOption,
    AssignmentQuestionVariant,
    AssignmentResponse,
    SectionMember,
)
from app.roles import MANAGE_ROLES
from app.services.assignment_grading import score_response
from app.services.assignment_snapshot import build_snapshot
from app.services.institutes import get_membership
from app.services.sections import require_section_access, require_section_student, require_section_teacher
from app.services.user_identity import enrich_rows

QUESTION_TYPES = frozenset(
    {"single_choice", "short_text", "essay", "fill_blank", "match_pairs", "order_items"}
)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _flip_scheduled(db: Session, row: Assignment) -> None:
    if row.publish_state != "scheduled":
        return
    if row.publish_at and row.publish_at <= _utcnow():
        row.publish_state = "published"
        db.add(row)


def _is_published(row: Assignment) -> bool:
    if row.publish_state == "published":
        return True
    if row.publish_state == "scheduled" and row.publish_at and row.publish_at <= _utcnow():
        return True
    return False


def _can_view_draft(db: Session, institute_id: str, user_id: str, author_id: str) -> bool:
    if user_id == author_id:
        return True
    member = get_membership(db, institute_id, user_id)
    return bool(member and member.role in MANAGE_ROLES)


def _audience_student_ids(db: Session, assignment_id: str) -> set[str]:
    return set(
        db.scalars(
            select(AssignmentAudienceStudent.student_id).where(
                AssignmentAudienceStudent.assignment_id == assignment_id
            )
        )
    )


def _in_audience(db: Session, row: Assignment, student_id: str) -> bool:
    if row.audience_type != "students":
        return True
    return student_id in _audience_student_ids(db, row.id)


def _attempt_counts(db: Session, assignment_id: str) -> dict[str, int]:
    rows = db.execute(
        select(AssignmentAttempt.status, func.count())
        .where(AssignmentAttempt.assignment_id == assignment_id)
        .group_by(AssignmentAttempt.status)
    )
    return {status: count for status, count in rows}


def _assignment_dict(
    db: Session,
    row: Assignment,
    *,
    include_counts: bool = False,
) -> dict[str, Any]:
    _flip_scheduled(db, row)
    audience_ids = list(_audience_student_ids(db, row.id)) if row.audience_type == "students" else []
    out: dict[str, Any] = {
        "id": row.id,
        "sectionId": row.section_id,
        "title": row.title,
        "description": row.description,
        "assignmentType": row.assignment_type,
        "dueDate": row.due_date.isoformat() if row.due_date else None,
        "publishState": row.publish_state,
        "publishAt": row.publish_at.isoformat() if row.publish_at else None,
        "dueAt": row.due_at.isoformat() if row.due_at else None,
        "audienceType": row.audience_type,
        "audienceStudentIds": audience_ids,
        "instructions": row.instructions,
        "scoresVisible": row.scores_visible,
        "createdBy": row.created_by,
    }
    if include_counts:
        counts = _attempt_counts(db, row.id)
        out["submittedCount"] = counts.get("submitted", 0) + counts.get("graded", 0)
        out["gradedCount"] = counts.get("graded", 0)
    return out


def list_teacher_works(db: Session, section_id: str, user_id: str, bucket: str | None) -> list[dict]:
    section = require_section_teacher(db, section_id, user_id)
    rows = list(db.scalars(select(Assignment).where(Assignment.section_id == section_id)))
    for row in rows:
        _flip_scheduled(db, row)
    db.commit()
    items = []
    for row in rows:
        if row.publish_state == "draft":
            if not _can_view_draft(db, section.institute_id, user_id, row.created_by):
                continue
        if bucket == "draft" and row.publish_state != "draft":
            continue
        if bucket == "scheduled" and row.publish_state != "scheduled":
            continue
        if bucket == "live" and not _is_published(row):
            continue
        if bucket == "closed" and not (_is_published(row) and row.due_at and row.due_at < _utcnow()):
            continue
        items.append(_assignment_dict(db, row, include_counts=True))
    return items


def create_work(db: Session, section_id: str, user_id: str, body: dict) -> dict:
    require_section_teacher(db, section_id, user_id)
    row = Assignment(
        section_id=section_id,
        title=body.get("title") or "Untitled assignment",
        description=body.get("description") or "",
        assignment_type=body.get("assignmentType") or "assignment",
        created_by=user_id,
        publish_state="draft",
        audience_type=body.get("audienceType") or "section",
        instructions=body.get("instructions") or "",
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _assignment_dict(db, row)


def get_work(db: Session, assignment_id: str, user_id: str) -> dict:
    row = db.get(Assignment, assignment_id)
    if not row:
        raise ValueError("Assignment not found")
    section = require_section_access(db, row.section_id, user_id)
    if row.publish_state == "draft" and not _can_view_draft(
        db, section.institute_id, user_id, row.created_by
    ):
        raise PermissionError("Draft not visible")
    _flip_scheduled(db, row)
    db.commit()
    return _assignment_dict(db, row, include_counts=True)


def patch_work(db: Session, assignment_id: str, user_id: str, body: dict) -> dict:
    row = db.get(Assignment, assignment_id)
    if not row:
        raise ValueError("Assignment not found")
    require_section_teacher(db, row.section_id, user_id)
    if "title" in body:
        row.title = body["title"]
    if "description" in body:
        row.description = body["description"]
    if "instructions" in body:
        row.instructions = body["instructions"]
    if "audienceType" in body:
        row.audience_type = body["audienceType"]
    if "dueAt" in body:
        row.due_at = _parse_dt(body["dueAt"])
    if "publishAt" in body:
        row.publish_at = _parse_dt(body["publishAt"])
    if "audienceStudentIds" in body:
        db.execute(
            delete(AssignmentAudienceStudent).where(
                AssignmentAudienceStudent.assignment_id == assignment_id
            )
        )
        for sid in body["audienceStudentIds"] or []:
            db.add(AssignmentAudienceStudent(assignment_id=assignment_id, student_id=sid))
    db.commit()
    db.refresh(row)
    return _assignment_dict(db, row, include_counts=True)


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    return datetime.fromisoformat(value)


def replace_questions(db: Session, assignment_id: str, user_id: str, questions: list[dict]) -> list[dict]:
    row = db.get(Assignment, assignment_id)
    if not row:
        raise ValueError("Assignment not found")
    require_section_teacher(db, row.section_id, user_id)
    old_ids = list(db.scalars(select(AssignmentQuestion.id).where(AssignmentQuestion.assignment_id == assignment_id)))
    if old_ids:
        db.execute(delete(AssignmentQuestion).where(AssignmentQuestion.id.in_(old_ids)))
    out = []
    for idx, q in enumerate(questions):
        qtype = q.get("type") or "essay"
        if qtype not in QUESTION_TYPES:
            raise ValueError(f"Unsupported question type: {qtype}")
        question = AssignmentQuestion(
            assignment_id=assignment_id,
            sort_order=q.get("sortOrder", idx),
            question_type=qtype,
            points=float(q.get("points") or 1),
            required=bool(q.get("required", True)),
        )
        db.add(question)
        db.flush()
        variants_out = []
        for vidx, v in enumerate(q.get("variants") or [{"stem": "", "metadata": {}}]):
            variant = AssignmentQuestionVariant(
                question_id=question.id,
                variant_index=vidx,
                stem_text=v.get("stem") or "",
                metadata_json=json.dumps(v.get("metadata") or {}),
            )
            db.add(variant)
            db.flush()
            options_out = []
            for opt in v.get("options") or []:
                option = AssignmentQuestionOption(
                    variant_id=variant.id,
                    option_key=opt.get("key") or "a",
                    label=opt.get("label") or "",
                    is_correct=bool(opt.get("isCorrect")),
                )
                db.add(option)
                options_out.append(
                    {
                        "key": option.option_key,
                        "label": option.label,
                        "isCorrect": option.is_correct,
                    }
                )
            variants_out.append(
                {
                    "id": variant.id,
                    "variantIndex": variant.variant_index,
                    "stem": variant.stem_text,
                    "metadata": json.loads(variant.metadata_json),
                    "options": options_out,
                }
            )
        out.append(
            {
                "id": question.id,
                "type": question.question_type,
                "sortOrder": question.sort_order,
                "points": question.points,
                "required": question.required,
                "variants": variants_out,
            }
        )
    db.commit()
    return out


def list_questions_teacher(db: Session, assignment_id: str, user_id: str) -> list[dict]:
    row = db.get(Assignment, assignment_id)
    if not row:
        raise ValueError("Assignment not found")
    require_section_teacher(db, row.section_id, user_id)
    return _load_questions(db, assignment_id, include_correct=True)


def _load_questions(db: Session, assignment_id: str, *, include_correct: bool) -> list[dict]:
    questions = list(
        db.scalars(
            select(AssignmentQuestion)
            .where(AssignmentQuestion.assignment_id == assignment_id)
            .order_by(AssignmentQuestion.sort_order)
        )
    )
    out = []
    for question in questions:
        variants = list(
            db.scalars(
                select(AssignmentQuestionVariant)
                .where(AssignmentQuestionVariant.question_id == question.id)
                .order_by(AssignmentQuestionVariant.variant_index)
            )
        )
        variants_out = []
        for variant in variants:
            options = list(
                db.scalars(
                    select(AssignmentQuestionOption).where(
                        AssignmentQuestionOption.variant_id == variant.id
                    )
                )
            )
            opt_out = []
            for o in options:
                item = {"key": o.option_key, "label": o.label}
                if include_correct:
                    item["isCorrect"] = o.is_correct
                opt_out.append(item)
            variants_out.append(
                {
                    "id": variant.id,
                    "variantIndex": variant.variant_index,
                    "stem": variant.stem_text,
                    "metadata": json.loads(variant.metadata_json or "{}"),
                    "options": opt_out,
                }
            )
        out.append(
            {
                "id": question.id,
                "type": question.question_type,
                "sortOrder": question.sort_order,
                "points": question.points,
                "required": question.required,
                "variants": variants_out,
            }
        )
    return out


def publish_work(db: Session, assignment_id: str, user_id: str, publish_at: datetime | None) -> dict:
    row = db.get(Assignment, assignment_id)
    if not row:
        raise ValueError("Assignment not found")
    require_section_teacher(db, row.section_id, user_id)
    if publish_at and publish_at > _utcnow():
        row.publish_state = "scheduled"
        row.publish_at = publish_at
    else:
        row.publish_state = "published"
        row.publish_at = publish_at or _utcnow()
    db.commit()
    db.refresh(row)
    return _assignment_dict(db, row, include_counts=True)


def unpublish_work(db: Session, assignment_id: str, user_id: str) -> dict:
    row = db.get(Assignment, assignment_id)
    if not row:
        raise ValueError("Assignment not found")
    require_section_teacher(db, row.section_id, user_id)
    submitted = db.scalar(
        select(func.count())
        .select_from(AssignmentAttempt)
        .where(
            AssignmentAttempt.assignment_id == assignment_id,
            AssignmentAttempt.status.in_(("submitted", "graded")),
        )
    )
    if submitted and submitted > 0:
        raise ValueError("Cannot unpublish after submissions exist")
    row.publish_state = "draft"
    row.publish_at = None
    db.commit()
    db.refresh(row)
    return _assignment_dict(db, row)


def list_assigned_student(db: Session, section_id: str, user_id: str) -> list[dict]:
    require_section_student(db, section_id, user_id)
    rows = list(db.scalars(select(Assignment).where(Assignment.section_id == section_id)))
    items = []
    for row in rows:
        _flip_scheduled(db, row)
        if not _is_published(row):
            continue
        if not _in_audience(db, row, user_id):
            continue
        attempt = db.scalar(
            select(AssignmentAttempt).where(
                AssignmentAttempt.assignment_id == row.id,
                AssignmentAttempt.student_id == user_id,
            )
        )
        items.append(
            {
                **_assignment_dict(db, row),
                "attemptStatus": attempt.status if attempt else None,
                "dueClosed": bool(row.due_at and row.due_at < _utcnow()),
            }
        )
    db.commit()
    return items


def get_or_create_attempt(db: Session, assignment_id: str, user_id: str) -> dict:
    row = db.get(Assignment, assignment_id)
    if not row:
        raise ValueError("Assignment not found")
    require_section_student(db, row.section_id, user_id)
    _flip_scheduled(db, row)
    if not _is_published(row):
        raise PermissionError("Assignment not published")
    if not _in_audience(db, row, user_id):
        raise PermissionError("Not in audience")
    if row.due_at and row.due_at < _utcnow():
        raise PermissionError("Due date passed")
    attempt = db.scalar(
        select(AssignmentAttempt).where(
            AssignmentAttempt.assignment_id == assignment_id,
            AssignmentAttempt.student_id == user_id,
        )
    )
    if not attempt:
        questions = list(
            db.scalars(select(AssignmentQuestion).where(AssignmentQuestion.assignment_id == assignment_id))
        )
        snapshot = build_snapshot(db, assignment_id, user_id, questions)
        attempt = AssignmentAttempt(
            assignment_id=assignment_id,
            student_id=user_id,
            snapshot_json=json.dumps(snapshot),
            status="in_progress",
        )
        db.add(attempt)
        db.commit()
        db.refresh(attempt)
    snapshot = json.loads(attempt.snapshot_json)
    responses = {
        r.question_id: json.loads(r.answer_json)
        for r in db.scalars(select(AssignmentResponse).where(AssignmentResponse.attempt_id == attempt.id))
    }
    return {
        "attemptId": attempt.id,
        "status": attempt.status,
        "snapshot": snapshot,
        "responses": responses,
        "score": attempt.score,
        "maxScore": attempt.max_score,
        "scoresVisible": row.scores_visible and attempt.status == "graded",
    }


def save_responses(db: Session, assignment_id: str, user_id: str, answers: dict[str, Any]) -> dict:
    attempt_row = _require_open_attempt(db, assignment_id, user_id)
    for qid, answer in answers.items():
        existing = db.scalar(
            select(AssignmentResponse).where(
                AssignmentResponse.attempt_id == attempt_row.id,
                AssignmentResponse.question_id == qid,
            )
        )
        if existing:
            existing.answer_json = json.dumps(answer)
        else:
            db.add(
                AssignmentResponse(
                    attempt_id=attempt_row.id,
                    question_id=qid,
                    answer_json=json.dumps(answer),
                )
            )
    db.commit()
    return get_or_create_attempt(db, assignment_id, user_id)


def submit_attempt(db: Session, assignment_id: str, user_id: str) -> dict:
    row = db.get(Assignment, assignment_id)
    if not row:
        raise ValueError("Assignment not found")
    attempt_row = _require_open_attempt(db, assignment_id, user_id)
    if row.due_at and row.due_at < _utcnow():
        raise PermissionError("Due date passed")
    snapshot = json.loads(attempt_row.snapshot_json)
    max_score = 0.0
    total = 0.0
    for item in snapshot.get("questions") or []:
        q = db.get(AssignmentQuestion, item["questionId"])
        if not q:
            continue
        max_score += float(q.points or 0)
        resp = db.scalar(
            select(AssignmentResponse).where(
                AssignmentResponse.attempt_id == attempt_row.id,
                AssignmentResponse.question_id == q.id,
            )
        )
        answer = json.loads(resp.answer_json) if resp else None
        auto = score_response(db, q, item["variantId"], answer)
        if resp:
            resp.auto_score = auto
        if auto is not None:
            total += auto
    attempt_row.status = "submitted"
    attempt_row.submitted_at = _utcnow()
    attempt_row.max_score = max_score
    attempt_row.score = total if _all_objective(snapshot, db) else total
    db.commit()
    return get_or_create_attempt(db, assignment_id, user_id)


def _all_objective(snapshot: dict, db: Session) -> bool:
    for item in snapshot.get("questions") or []:
        q = db.get(AssignmentQuestion, item["questionId"])
        if q and q.question_type == "essay":
            return False
    return True


def _require_open_attempt(db: Session, assignment_id: str, user_id: str) -> AssignmentAttempt:
    row = db.get(Assignment, assignment_id)
    if not row:
        raise ValueError("Assignment not found")
    require_section_student(db, row.section_id, user_id)
    attempt = db.scalar(
        select(AssignmentAttempt).where(
            AssignmentAttempt.assignment_id == assignment_id,
            AssignmentAttempt.student_id == user_id,
        )
    )
    if not attempt or attempt.status != "in_progress":
        raise ValueError("No open attempt")
    return attempt


def list_submissions(db: Session, assignment_id: str, user_id: str) -> list[dict]:
    row = db.get(Assignment, assignment_id)
    if not row:
        raise ValueError("Assignment not found")
    require_section_teacher(db, row.section_id, user_id)
    students = list(
        db.scalars(
            select(SectionMember).where(
                SectionMember.section_id == row.section_id,
                SectionMember.member_type == "student",
            )
        )
    )
    if row.audience_type == "students":
        allowed = _audience_student_ids(db, assignment_id)
        students = [s for s in students if s.user_id in allowed]
    attempts = {
        a.student_id: a
        for a in db.scalars(select(AssignmentAttempt).where(AssignmentAttempt.assignment_id == assignment_id))
    }
    names = {r["userId"]: r for r in enrich_rows([{"userId": s.user_id} for s in students])}
    out = []
    for student in students:
        att = attempts.get(student.user_id)
        info = names.get(student.user_id, {})
        out.append(
            {
                "studentId": student.user_id,
                "displayName": info.get("displayName") or info.get("username"),
                "attemptId": att.id if att else None,
                "status": att.status if att else "not_started",
                "submittedAt": att.submitted_at.isoformat() if att and att.submitted_at else None,
                "score": att.score if att else None,
                "maxScore": att.max_score if att else None,
            }
        )
    return out


def grade_attempt(
    db: Session,
    assignment_id: str,
    attempt_id: str,
    user_id: str,
    body: dict,
) -> dict:
    row = db.get(Assignment, assignment_id)
    if not row:
        raise ValueError("Assignment not found")
    require_section_teacher(db, row.section_id, user_id)
    attempt = db.get(AssignmentAttempt, attempt_id)
    if not attempt or attempt.assignment_id != assignment_id:
        raise ValueError("Attempt not found")
    for item in body.get("responses") or []:
        qid = item.get("questionId")
        resp = db.scalar(
            select(AssignmentResponse).where(
                AssignmentResponse.attempt_id == attempt_id,
                AssignmentResponse.question_id == qid,
            )
        )
        if not resp:
            continue
        if "teacherScore" in item:
            resp.teacher_score = item["teacherScore"]
        if "feedback" in item:
            resp.feedback = item["feedback"] or ""
    total = 0.0
    max_score = 0.0
    snapshot = json.loads(attempt.snapshot_json)
    for qitem in snapshot.get("questions") or []:
        q = db.get(AssignmentQuestion, qitem["questionId"])
        if not q:
            continue
        max_score += float(q.points or 0)
        resp = db.scalar(
            select(AssignmentResponse).where(
                AssignmentResponse.attempt_id == attempt_id,
                AssignmentResponse.question_id == q.id,
            )
        )
        if not resp:
            continue
        if resp.teacher_score is not None:
            total += float(resp.teacher_score)
        elif resp.auto_score is not None:
            total += float(resp.auto_score)
    attempt.score = total
    attempt.max_score = max_score
    attempt.status = "graded"
    if body.get("scoresVisible") is True:
        row.scores_visible = True
    db.commit()
    return {"attemptId": attempt.id, "status": attempt.status, "score": total, "maxScore": max_score}
