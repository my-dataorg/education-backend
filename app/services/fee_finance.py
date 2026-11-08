from __future__ import annotations

from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    FeePlan,
    FeeStructure,
    InstituteExpense,
    Payment,
    Section,
    SectionFeeDefault,
    SectionMember,
    StudentFee,
)
from app.services.fees import _require_fee_manage, assign_student_fee, ensure_default_fee_structure
from app.services.institutes import require_membership


def effective_amount_paise(base_paise: int, plan: FeePlan | None) -> int:
    if not plan or plan.discount_percent <= 0:
        return base_paise
    return int(base_paise * (100 - plan.discount_percent) / 100)


def plan_to_dict(plan: FeePlan) -> dict:
    return {
        "id": plan.id,
        "instituteId": plan.institute_id,
        "name": plan.name,
        "installmentCount": plan.installment_count,
        "discountPercent": plan.discount_percent,
        "lateFeePaise": plan.late_fee_paise,
        "dueScheduleNotes": plan.due_schedule_notes or "",
    }


def list_fee_plans(db: Session, institute_id: str, user_id: str) -> list[FeePlan]:
    require_membership(db, institute_id, user_id)
    return list(
        db.scalars(
            select(FeePlan).where(FeePlan.institute_id == institute_id).order_by(FeePlan.name)
        )
    )


def create_fee_plan(
    db: Session,
    institute_id: str,
    user_id: str,
    name: str,
    installment_count: int,
    discount_percent: int,
    late_fee_paise: int,
    due_schedule_notes: str = "",
) -> FeePlan:
    _require_fee_manage(db, institute_id, user_id)
    if installment_count < 1:
        raise ValueError("installmentCount must be at least 1")
    if not 0 <= discount_percent <= 100:
        raise ValueError("discountPercent must be 0–100")
    row = FeePlan(
        institute_id=institute_id,
        name=name.strip(),
        installment_count=installment_count,
        discount_percent=discount_percent,
        late_fee_paise=max(late_fee_paise, 0),
        due_schedule_notes=(due_schedule_notes or "").strip()[:500],
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def update_fee_plan(
    db: Session,
    institute_id: str,
    user_id: str,
    plan_id: str,
    *,
    name: str | None,
    installment_count: int | None,
    discount_percent: int | None,
    late_fee_paise: int | None,
    due_schedule_notes: str | None = None,
) -> FeePlan:
    _require_fee_manage(db, institute_id, user_id)
    row = db.get(FeePlan, plan_id)
    if not row or row.institute_id != institute_id:
        raise ValueError("Fee plan not found")
    if name is not None:
        row.name = name.strip()
    if installment_count is not None:
        if installment_count < 1:
            raise ValueError("installmentCount must be at least 1")
        row.installment_count = installment_count
    if discount_percent is not None:
        if not 0 <= discount_percent <= 100:
            raise ValueError("discountPercent must be 0–100")
        row.discount_percent = discount_percent
    if late_fee_paise is not None:
        row.late_fee_paise = max(late_fee_paise, 0)
    if due_schedule_notes is not None:
        row.due_schedule_notes = due_schedule_notes.strip()[:500]
    db.commit()
    db.refresh(row)
    return row


def delete_fee_plan(db: Session, institute_id: str, user_id: str, plan_id: str) -> None:
    _require_fee_manage(db, institute_id, user_id)
    row = db.get(FeePlan, plan_id)
    if not row or row.institute_id != institute_id:
        raise ValueError("Fee plan not found")
    db.delete(row)
    db.commit()


def _get_section(db: Session, institute_id: str, section_id: str) -> Section:
    section = db.get(Section, section_id)
    if not section or section.institute_id != institute_id:
        raise ValueError("Section not found")
    return section


def _resolve_fee_structure_id(
    db: Session, institute_id: str, user_id: str, fee_structure_id: str | None
) -> str:
    if fee_structure_id:
        row = db.get(FeeStructure, fee_structure_id)
        if not row or row.institute_id != institute_id:
            raise ValueError("Fee structure not found")
        return fee_structure_id
    return ensure_default_fee_structure(db, institute_id, user_id).id


def get_section_fee_default(db: Session, institute_id: str, user_id: str, section_id: str) -> dict:
    require_membership(db, institute_id, user_id)
    _get_section(db, institute_id, section_id)
    row = db.get(SectionFeeDefault, section_id)
    if not row:
        return {
            "sectionId": section_id,
            "amountPaise": 0,
            "feePlanId": None,
            "feeStructureId": None,
            "feePlan": None,
        }
    plan = db.get(FeePlan, row.fee_plan_id) if row.fee_plan_id else None
    return {
        "sectionId": section_id,
        "amountPaise": row.amount_paise,
        "feePlanId": row.fee_plan_id,
        "feeStructureId": row.fee_structure_id,
        "feePlan": plan_to_dict(plan) if plan else None,
    }


def put_section_fee_default(
    db: Session,
    institute_id: str,
    user_id: str,
    section_id: str,
    amount_paise: int,
    fee_plan_id: str | None,
    fee_structure_id: str | None = None,
) -> dict:
    _require_fee_manage(db, institute_id, user_id)
    _get_section(db, institute_id, section_id)
    if amount_paise < 0:
        raise ValueError("amountPaise must be non-negative")
    if fee_plan_id:
        plan = db.get(FeePlan, fee_plan_id)
        if not plan or plan.institute_id != institute_id:
            raise ValueError("Fee plan not found")
    structure_id: str | None = None
    if fee_structure_id:
        structure_id = _resolve_fee_structure_id(db, institute_id, user_id, fee_structure_id)
    row = db.get(SectionFeeDefault, section_id)
    if row:
        row.amount_paise = amount_paise
        row.fee_plan_id = fee_plan_id
        row.institute_id = institute_id
        if structure_id:
            row.fee_structure_id = structure_id
    else:
        if not structure_id:
            structure_id = _resolve_fee_structure_id(db, institute_id, user_id, None)
        row = SectionFeeDefault(
            section_id=section_id,
            institute_id=institute_id,
            amount_paise=amount_paise,
            fee_plan_id=fee_plan_id,
            fee_structure_id=structure_id,
        )
        db.add(row)
    db.commit()
    return get_section_fee_default(db, institute_id, user_id, section_id)


def apply_section_fee_defaults(
    db: Session,
    institute_id: str,
    user_id: str,
    section_id: str,
    fee_structure_id: str | None,
) -> int:
    """Assign section default fee + plan to each student in the section. Returns count updated."""
    _require_fee_manage(db, institute_id, user_id)
    _get_section(db, institute_id, section_id)
    default = db.get(SectionFeeDefault, section_id)
    if not default or default.amount_paise <= 0:
        raise ValueError("Set and save the class annual fee first (must be greater than zero)")
    resolved_structure = fee_structure_id or default.fee_structure_id
    fee_structure_id = _resolve_fee_structure_id(db, institute_id, user_id, resolved_structure)
    if default.fee_structure_id != fee_structure_id:
        default.fee_structure_id = fee_structure_id
        db.commit()
    plan = db.get(FeePlan, default.fee_plan_id) if default.fee_plan_id else None
    billed = effective_amount_paise(default.amount_paise, plan)
    student_ids = db.scalars(
        select(SectionMember.user_id).where(
            SectionMember.section_id == section_id, SectionMember.member_type == "student"
        )
    ).all()
    count = 0
    for student_id in student_ids:
        row = assign_student_fee(db, institute_id, user_id, student_id, fee_structure_id, billed)
        row.fee_plan_id = default.fee_plan_id
        row.section_id = section_id
        db.commit()
        db.refresh(row)
        count += 1
    return count


def expense_to_dict(row: InstituteExpense) -> dict:
    return {
        "id": row.id,
        "instituteId": row.institute_id,
        "category": row.category,
        "kind": row.kind,
        "label": row.label,
        "amountPaise": row.amount_paise,
        "expenseDate": row.expense_date.isoformat(),
        "teacherUserId": row.teacher_user_id,
        "notes": row.notes,
        "recordedBy": row.recorded_by,
        "createdAt": row.created_at,
    }


def list_expenses(
    db: Session,
    institute_id: str,
    user_id: str,
    category: str | None,
) -> list[InstituteExpense]:
    member = require_membership(db, institute_id, user_id)
    stmt = select(InstituteExpense).where(InstituteExpense.institute_id == institute_id)
    if member.role in {"teacher", "lecturer", "professor"}:
        stmt = stmt.where(
            InstituteExpense.teacher_user_id == user_id,
            InstituteExpense.category == "staff",
        )
    elif category:
        stmt = stmt.where(InstituteExpense.category == category)
    elif member.role not in {"owner", "admin", "principal", "accountant"}:
        raise PermissionError("Not allowed to view institute expenses")
    return list(db.scalars(stmt.order_by(InstituteExpense.expense_date.desc(), InstituteExpense.id.desc())))


def create_expense(
    db: Session,
    institute_id: str,
    user_id: str,
    *,
    category: str,
    kind: str,
    label: str,
    amount_paise: int,
    expense_date: date,
    teacher_user_id: str | None,
    notes: str,
) -> InstituteExpense:
    _require_fee_manage(db, institute_id, user_id)
    if category not in {"staff", "institute"}:
        raise ValueError("category must be staff or institute")
    if amount_paise <= 0:
        raise ValueError("amountPaise must be positive")
    if category == "staff" and not teacher_user_id:
        raise ValueError("teacherUserId required for staff expenses")
    row = InstituteExpense(
        institute_id=institute_id,
        category=category,
        kind=kind,
        label=label.strip(),
        amount_paise=amount_paise,
        expense_date=expense_date,
        teacher_user_id=teacher_user_id,
        notes=notes.strip(),
        recorded_by=user_id,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def enrich_due_row(db: Session, fee: StudentFee) -> dict:
    plan = db.get(FeePlan, fee.fee_plan_id) if fee.fee_plan_id else None
    balance = max(fee.amount_paise - fee.paid_paise, 0)
    installment_count = plan.installment_count if plan else 1
    per_installment = fee.amount_paise // installment_count if installment_count else fee.amount_paise
    return {
        "studentId": fee.student_id,
        "feeStructureId": fee.fee_structure_id,
        "amountPaise": fee.amount_paise,
        "paidPaise": fee.paid_paise,
        "balancePaise": balance,
        "feePlanId": fee.fee_plan_id,
        "sectionId": fee.section_id,
        "feePlanName": plan.name if plan else None,
        "installmentCount": installment_count,
        "discountPercent": plan.discount_percent if plan else 0,
        "lateFeePaise": plan.late_fee_paise if plan else 0,
        "installmentAmountPaise": per_installment,
    }


def payment_summary(payment: Payment) -> dict:
    return {
        "id": payment.id,
        "amountPaise": payment.amount_paise,
        "method": payment.method,
        "reference": payment.reference,
        "receiptNumber": payment.receipt_number,
        "createdAt": payment.created_at,
    }


def list_section_fee_defaults_overview(db: Session, institute_id: str, user_id: str) -> list[dict]:
    _require_fee_manage(db, institute_id, user_id)
    sections = list(
        db.scalars(
            select(Section).where(Section.institute_id == institute_id).order_by(Section.class_name, Section.name)
        )
    )
    defaults = {
        row.section_id: row
        for row in db.scalars(select(SectionFeeDefault).where(SectionFeeDefault.institute_id == institute_id))
    }
    out: list[dict] = []
    for section in sections:
        row = defaults.get(section.id)
        plan = db.get(FeePlan, row.fee_plan_id) if row and row.fee_plan_id else None
        out.append(
            {
                "sectionId": section.id,
                "className": section.class_name,
                "sectionName": section.name,
                "amountPaise": row.amount_paise if row else 0,
                "feePlanId": row.fee_plan_id if row else None,
                "feeStructureId": row.fee_structure_id if row else None,
                "feePlan": plan_to_dict(plan) if plan else None,
            }
        )
    return out


def get_section_fee_ledger(db: Session, institute_id: str, user_id: str, section_id: str) -> dict:
    member = require_membership(db, institute_id, user_id)
    if member.role not in {"owner", "admin", "principal", "accountant"}:
        raise PermissionError("Fee ledger requires finance staff role")
    _get_section(db, institute_id, section_id)
    section_default = get_section_fee_default(db, institute_id, user_id, section_id)

    student_ids = list(
        db.scalars(
            select(SectionMember.user_id).where(
                SectionMember.section_id == section_id,
                SectionMember.member_type == "student",
            )
        )
    )
    students_out: list[dict] = []
    for student_id in student_ids:
        fees = list(
            db.scalars(
                select(StudentFee).where(
                    StudentFee.institute_id == institute_id,
                    StudentFee.student_id == student_id,
                )
            )
        )
        fee_lines = [enrich_due_row(db, fee) for fee in fees]
        balance = sum(line["balancePaise"] for line in fee_lines)
        paid_total = sum(line["paidPaise"] for line in fee_lines)
        billed_total = sum(line["amountPaise"] for line in fee_lines)
        payments = list(
            db.scalars(
                select(Payment)
                .where(Payment.institute_id == institute_id, Payment.student_id == student_id)
                .order_by(Payment.created_at.desc())
                .limit(25)
            )
        )
        students_out.append(
            {
                "studentId": student_id,
                "billedPaise": billed_total,
                "paidPaise": paid_total,
                "balancePaise": balance,
                "fees": fee_lines,
                "payments": [payment_summary(p) for p in payments],
                "status": "paid" if balance == 0 and billed_total > 0 else "due" if balance > 0 else "unassigned",
            }
        )

    return {
        "sectionId": section_id,
        "sectionDefault": section_default,
        "students": students_out,
    }
