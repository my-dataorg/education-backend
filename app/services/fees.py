from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import FeeStructure, Payment, StudentFee
from app.roles import MANAGE_ROLES
from app.services.institutes import require_membership


def _require_fee_manage(db: Session, institute_id: str, user_id: str) -> None:
    member = require_membership(db, institute_id, user_id)
    if member.role not in MANAGE_ROLES and member.role not in {"principal", "accountant"}:
        raise PermissionError("Fee management role required")


def list_fee_structures(db: Session, institute_id: str, user_id: str) -> list[FeeStructure]:
    _require_fee_manage(db, institute_id, user_id)
    return list(
        db.scalars(
            select(FeeStructure)
            .where(FeeStructure.institute_id == institute_id)
            .order_by(FeeStructure.name)
        )
    )


def create_fee_structure(
    db: Session, institute_id: str, user_id: str, name: str, amount_paise: int, academic_year_id: str | None
) -> FeeStructure:
    _require_fee_manage(db, institute_id, user_id)
    row = FeeStructure(
        institute_id=institute_id,
        name=name,
        amount_paise=amount_paise,
        academic_year_id=academic_year_id,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def assign_student_fee(
    db: Session, institute_id: str, user_id: str, student_id: str, fee_structure_id: str, amount_paise: int | None
) -> StudentFee:
    _require_fee_manage(db, institute_id, user_id)
    structure = db.get(FeeStructure, fee_structure_id)
    if not structure or structure.institute_id != institute_id:
        raise ValueError("Fee structure not found")
    billed = amount_paise if amount_paise is not None else structure.amount_paise
    existing = db.scalar(
        select(StudentFee).where(
            StudentFee.institute_id == institute_id,
            StudentFee.student_id == student_id,
            StudentFee.fee_structure_id == fee_structure_id,
        )
    )
    if existing:
        existing.amount_paise = billed
        db.commit()
        db.refresh(existing)
        return existing
    row = StudentFee(
        institute_id=institute_id,
        student_id=student_id,
        fee_structure_id=fee_structure_id,
        amount_paise=billed,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def list_dues(db: Session, institute_id: str, user_id: str, student_id: str | None = None) -> list[dict]:
    member = require_membership(db, institute_id, user_id)
    if member.role == "student":
        student_id = user_id
    elif student_id is None:
        _require_fee_manage(db, institute_id, user_id)
    else:
        _require_fee_manage(db, institute_id, user_id)

    stmt = select(StudentFee).where(StudentFee.institute_id == institute_id)
    if student_id:
        stmt = stmt.where(StudentFee.student_id == student_id)
    rows = db.scalars(stmt.order_by(StudentFee.student_id))
    out: list[dict] = []
    for fee in rows:
        balance = max(fee.amount_paise - fee.paid_paise, 0)
        out.append(
            {
                "studentId": fee.student_id,
                "feeStructureId": fee.fee_structure_id,
                "amountPaise": fee.amount_paise,
                "paidPaise": fee.paid_paise,
                "balancePaise": balance,
            }
        )
    return out


def _next_receipt_number(db: Session, institute_id: str) -> str:
    count = db.scalar(
        select(func.count()).select_from(Payment).where(Payment.institute_id == institute_id)
    )
    return f"RCP-{institute_id[:8]}-{int(count or 0) + 1:06d}"


def record_payment(
    db: Session,
    institute_id: str,
    user_id: str,
    student_id: str,
    amount_paise: int,
    method: str,
    reference: str,
) -> Payment:
    _require_fee_manage(db, institute_id, user_id)
    if amount_paise <= 0:
        raise ValueError("Payment amount must be positive")
    receipt_number = _next_receipt_number(db, institute_id)
    payment = Payment(
        institute_id=institute_id,
        student_id=student_id,
        amount_paise=amount_paise,
        method=method,
        reference=reference,
        receipt_number=receipt_number,
        recorded_by=user_id,
    )
    db.add(payment)
    remaining = amount_paise
    fees = list(
        db.scalars(
            select(StudentFee)
            .where(
                StudentFee.institute_id == institute_id,
                StudentFee.student_id == student_id,
                StudentFee.amount_paise > StudentFee.paid_paise,
            )
            .order_by(StudentFee.id)
        )
    )
    for fee in fees:
        if remaining <= 0:
            break
        due = fee.amount_paise - fee.paid_paise
        applied = min(due, remaining)
        fee.paid_paise += applied
        remaining -= applied
    db.commit()
    db.refresh(payment)
    return payment


def get_receipt(db: Session, institute_id: str, receipt_id: str, user_id: str) -> Payment:
    member = require_membership(db, institute_id, user_id)
    payment = db.scalar(
        select(Payment).where(
            Payment.institute_id == institute_id,
            (Payment.id == receipt_id) | (Payment.receipt_number == receipt_id),
        )
    )
    if not payment:
        raise ValueError("Receipt not found")
    if member.role == "student" and payment.student_id != user_id:
        raise PermissionError("Not allowed to view this receipt")
    if member.role not in MANAGE_ROLES and member.role not in {"principal", "accountant", "student"}:
        raise PermissionError("Not allowed to view receipts")
    return payment
