from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import FeeStructure, Payment, StudentFee
from app.roles import MANAGE_ROLES
from app.services.institutes import require_membership


def _require_fee_manage(db: Session, institute_id: str, user_id: str) -> None:
    member = require_membership(db, institute_id, user_id)
    if member.role not in MANAGE_ROLES and member.role not in {"principal", "accountant"}:
        raise PermissionError("Fee management role required")


DEFAULT_FEE_HEAD_NAME = "Annual tuition"


def ensure_default_fee_structure(db: Session, institute_id: str, user_id: str) -> FeeStructure:
    _require_fee_manage(db, institute_id, user_id)
    row = db.scalar(
        select(FeeStructure)
        .where(FeeStructure.institute_id == institute_id)
        .order_by(FeeStructure.name)
        .limit(1)
    )
    if row:
        return row
    return create_fee_structure(db, institute_id, user_id, DEFAULT_FEE_HEAD_NAME, 0, None)


def list_fee_structures(db: Session, institute_id: str, user_id: str) -> list[FeeStructure]:
    _require_fee_manage(db, institute_id, user_id)
    rows = list(
        db.scalars(
            select(FeeStructure)
            .where(FeeStructure.institute_id == institute_id)
            .order_by(FeeStructure.name)
        )
    )
    if not rows:
        return [ensure_default_fee_structure(db, institute_id, user_id)]
    return rows


def create_fee_structure(
    db: Session,
    institute_id: str,
    user_id: str,
    name: str,
    amount_paise: int,
    academic_year_id: str | None,
    org_node_id: str | None = None,
) -> FeeStructure:
    _require_fee_manage(db, institute_id, user_id)
    row = FeeStructure(
        institute_id=institute_id,
        name=name,
        amount_paise=amount_paise,
        academic_year_id=academic_year_id,
        org_node_id=org_node_id,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def assign_student_fee(
    db: Session,
    institute_id: str,
    user_id: str,
    student_id: str,
    fee_structure_id: str,
    amount_paise: int | None,
    fee_plan_id: str | None = None,
    section_id: str | None = None,
    payment_notes: str = "",
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
        if fee_plan_id is not None:
            existing.fee_plan_id = fee_plan_id
        if section_id is not None:
            existing.section_id = section_id
        if payment_notes:
            existing.payment_notes = payment_notes.strip()[:500]
        db.commit()
        db.refresh(existing)
        return existing
    row = StudentFee(
        institute_id=institute_id,
        student_id=student_id,
        fee_structure_id=fee_structure_id,
        amount_paise=billed,
        fee_plan_id=fee_plan_id,
        section_id=section_id,
        payment_notes=payment_notes.strip()[:500],
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
    from app.services.fee_finance import enrich_due_row

    return [enrich_due_row(db, fee) for fee in rows]


def _next_receipt_number(db: Session, institute_id: str) -> str:
    count = db.scalar(
        select(func.count()).select_from(Payment).where(Payment.institute_id == institute_id)
    )
    return f"RCP-{institute_id[:8]}-{int(count or 0) + 1:06d}"


def _student_fee_row(
    db: Session, institute_id: str, student_id: str, fee_structure_id: str
) -> StudentFee | None:
    return db.scalar(
        select(StudentFee).where(
            StudentFee.institute_id == institute_id,
            StudentFee.student_id == student_id,
            StudentFee.fee_structure_id == fee_structure_id,
        )
    )


def _billed_paise_for_structure(
    db: Session,
    institute_id: str,
    section_id: str | None,
    student_id: str,
    fee_structure_id: str,
    fallback_paise: int,
) -> int:
    if section_id:
        from app.services.fee_finance import student_fee_lines_for_detail

        for line in student_fee_lines_for_detail(db, institute_id, section_id, student_id):
            if line["feeStructureId"] == fee_structure_id:
                return int(line["amountPaise"])
    structure = db.get(FeeStructure, fee_structure_id)
    if structure and structure.institute_id == institute_id:
        return int(structure.amount_paise)
    return fallback_paise


def _ensure_student_fee_row(
    db: Session,
    institute_id: str,
    student_id: str,
    fee_structure_id: str,
    billed_paise: int,
    section_id: str | None,
) -> StudentFee:
    structure = db.get(FeeStructure, fee_structure_id)
    if not structure or structure.institute_id != institute_id:
        raise ValueError("Fee structure not found")
    row = _student_fee_row(db, institute_id, student_id, fee_structure_id)
    if row:
        if row.amount_paise < billed_paise:
            row.amount_paise = billed_paise
        if section_id:
            row.section_id = section_id
        return row
    row = StudentFee(
        institute_id=institute_id,
        student_id=student_id,
        fee_structure_id=fee_structure_id,
        amount_paise=billed_paise,
        section_id=section_id,
    )
    db.add(row)
    db.flush()
    return row


def record_payment(
    db: Session,
    institute_id: str,
    user_id: str,
    student_id: str,
    amount_paise: int | None,
    method: str,
    reference: str,
    *,
    section_id: str | None = None,
    allocations: list[dict] | None = None,
) -> Payment:
    _require_fee_manage(db, institute_id, user_id)
    allocs = allocations or []
    if allocs:
        total = sum(int(a["amountPaise"]) for a in allocs)
        if total <= 0:
            raise ValueError("Payment amount must be positive")
        amount_paise = total
    elif not amount_paise or amount_paise <= 0:
        raise ValueError("Payment amount must be positive")
    else:
        amount_paise = int(amount_paise)

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

    if allocs:
        for raw in allocs:
            fs_id = raw["feeStructureId"]
            pay_amt = int(raw["amountPaise"])
            if pay_amt <= 0:
                continue
            billed = _billed_paise_for_structure(
                db, institute_id, section_id, student_id, fs_id, pay_amt
            )
            row = _ensure_student_fee_row(
                db, institute_id, student_id, fs_id, billed, section_id
            )
            due = max(row.amount_paise - row.paid_paise, 0)
            applied = min(due, pay_amt) if due > 0 else pay_amt
            row.paid_paise += applied
            if row.amount_paise < row.paid_paise:
                row.amount_paise = row.paid_paise
    else:
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
