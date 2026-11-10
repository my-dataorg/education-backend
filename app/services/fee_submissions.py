from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import FeePaymentSubmission
from app.services.fee_finance import _get_section
from app.services.fees import _require_fee_manage, record_payment
from app.services.institutes import require_membership

MANAGE_ROLES = {"owner", "admin", "principal", "accountant"}


def submission_to_dict(row: FeePaymentSubmission) -> dict:
    return {
        "id": row.id,
        "instituteId": row.institute_id,
        "sectionId": row.section_id,
        "studentId": row.student_id,
        "amountPaise": row.amount_paise,
        "method": row.method,
        "reference": row.reference,
        "proofNotes": row.proof_notes,
        "status": row.status,
        "paymentId": row.payment_id,
        "submittedBy": row.submitted_by,
        "reviewedBy": row.reviewed_by,
        "createdAt": row.created_at,
        "reviewedAt": row.reviewed_at,
    }


def submit_payment_proof(
    db: Session,
    institute_id: str,
    user_id: str,
    section_id: str,
    amount_paise: int,
    method: str,
    reference: str,
    proof_notes: str,
    student_id: str | None = None,
) -> dict:
    member = require_membership(db, institute_id, user_id)
    target = student_id or user_id
    if member.role == "student" and target != user_id:
        raise PermissionError("Students can only submit for themselves")
    if member.role not in MANAGE_ROLES | {"student"} and target != user_id:
        raise PermissionError("Not allowed to submit payment proof")
    _get_section(db, institute_id, section_id)
    if amount_paise <= 0:
        raise ValueError("amountPaise must be positive")
    clean_method = (method or "upi").strip().lower()
    if clean_method not in {"cash", "upi", "bank"}:
        raise ValueError("method must be cash, upi, or bank")
    row = FeePaymentSubmission(
        institute_id=institute_id,
        section_id=section_id,
        student_id=target,
        amount_paise=amount_paise,
        method=clean_method,
        reference=(reference or "").strip()[:200],
        proof_notes=(proof_notes or "").strip()[:500],
        status="pending",
        submitted_by=user_id,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return submission_to_dict(row)


def list_section_payment_submissions(
    db: Session, institute_id: str, user_id: str, section_id: str, status: str | None = None
) -> list[dict]:
    member = require_membership(db, institute_id, user_id)
    if member.role not in MANAGE_ROLES | {"teacher"}:
        raise PermissionError("Not allowed")
    _get_section(db, institute_id, section_id)
    q = select(FeePaymentSubmission).where(
        FeePaymentSubmission.institute_id == institute_id,
        FeePaymentSubmission.section_id == section_id,
    )
    if status:
        q = q.where(FeePaymentSubmission.status == status)
    rows = list(db.scalars(q.order_by(FeePaymentSubmission.created_at.desc())))
    return [submission_to_dict(r) for r in rows]


def review_payment_submission(
    db: Session, institute_id: str, user_id: str, submission_id: str, approve: bool
) -> dict:
    _require_fee_manage(db, institute_id, user_id)
    row = db.get(FeePaymentSubmission, submission_id)
    if not row or row.institute_id != institute_id:
        raise ValueError("Submission not found")
    if row.status != "pending":
        raise ValueError("Submission already reviewed")
    now = datetime.now(timezone.utc)
    if approve:
        payment = record_payment(
            db,
            institute_id,
            user_id,
            row.student_id,
            row.amount_paise,
            row.method,
            row.reference or f"Proof #{row.id[:8]}",
        )
        row.status = "approved"
        row.payment_id = payment.id
    else:
        row.status = "rejected"
    row.reviewed_by = user_id
    row.reviewed_at = now
    db.commit()
    db.refresh(row)
    return submission_to_dict(row)


def pending_count_for_students(db: Session, institute_id: str, section_id: str, student_ids: list[str]) -> dict[str, int]:
    if not student_ids:
        return {}
    rows = list(
        db.scalars(
            select(FeePaymentSubmission).where(
                FeePaymentSubmission.institute_id == institute_id,
                FeePaymentSubmission.section_id == section_id,
                FeePaymentSubmission.status == "pending",
                FeePaymentSubmission.student_id.in_(student_ids),
            )
        )
    )
    out: dict[str, int] = {}
    for row in rows:
        out[row.student_id] = out.get(row.student_id, 0) + 1
    return out
