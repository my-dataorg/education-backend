from __future__ import annotations

from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    ClassFeeDefault,
    FeePlan,
    FeePlanInstallment,
    InstituteFeeDefault,
    Section,
    SectionFeeDefault,
    StudentFee,
    StudentFeeInstallment,
)
from app.services.fee_finance import effective_amount_paise, plan_to_dict
from app.services.org_fee import resolve_from_org_tree


def resolve_standard_fee(
    db: Session,
    institute_id: str,
    section_id: str,
    student_id: str,
    fee_structure_id: str | None = None,
) -> dict:
    """Priority: student → section → class → institute."""
    section = db.get(Section, section_id)
    if not section or section.institute_id != institute_id:
        raise ValueError("Section not found")

    student_fee = db.scalar(
        select(StudentFee).where(
            StudentFee.institute_id == institute_id,
            StudentFee.student_id == student_id,
            StudentFee.section_id == section_id,
        )
    )
    if fee_structure_id and student_fee and student_fee.fee_structure_id != fee_structure_id:
        student_fee = db.scalar(
            select(StudentFee).where(
                StudentFee.institute_id == institute_id,
                StudentFee.student_id == student_id,
                StudentFee.fee_structure_id == fee_structure_id,
            )
        )

    section_row = db.get(SectionFeeDefault, section_id)
    class_row = db.get(ClassFeeDefault, (institute_id, section.class_name or ""))
    institute_row = db.get(InstituteFeeDefault, institute_id)

    amount_paise = 0
    fee_plan_id: str | None = None
    fee_structure_id_resolved: str | None = None
    resolved_from = "none"

    org_hit = resolve_from_org_tree(db, institute_id, section_id, student_id)
    org_node_id: str | None = None
    org_node_label: str | None = None

    if student_fee and (student_fee.amount_paise > 0 or student_fee.fee_plan_id):
        amount_paise = student_fee.amount_paise
        resolved_from = "student"
    elif org_hit:
        amount_paise = org_hit["amountPaise"]
        resolved_from = org_hit["resolvedFrom"]
        org_node_id = org_hit.get("orgNodeId")
        org_node_label = org_hit.get("orgNodeLabel")
    else:
        layer_amounts = [
            ("section", section_row.amount_paise if section_row else 0, bool(section_row and section_row.amount_paise > 0)),
            (
                "class",
                class_row.amount_paise if class_row else 0,
                bool(class_row and class_row.amount_paise > 0),
            ),
            (
                "institute",
                institute_row.amount_paise if institute_row else 0,
                bool(institute_row and institute_row.amount_paise > 0),
            ),
        ]
        for name, amt, use in layer_amounts:
            if not use:
                continue
            amount_paise = amt
            resolved_from = name
            break

    def pick_plan_id() -> str | None:
        if student_fee and student_fee.fee_plan_id:
            return student_fee.fee_plan_id
        if org_hit and org_hit.get("feePlanId"):
            return org_hit["feePlanId"]
        if section_row and section_row.fee_plan_id:
            return section_row.fee_plan_id
        if class_row and class_row.fee_plan_id:
            return class_row.fee_plan_id
        if institute_row and institute_row.fee_plan_id:
            return institute_row.fee_plan_id
        return None

    def pick_structure_id() -> str | None:
        if student_fee and student_fee.fee_structure_id:
            return student_fee.fee_structure_id
        if org_hit and org_hit.get("feeStructureId"):
            return org_hit["feeStructureId"]
        if section_row and section_row.fee_structure_id:
            return section_row.fee_structure_id
        if class_row and class_row.fee_structure_id:
            return class_row.fee_structure_id
        if institute_row and institute_row.fee_structure_id:
            return institute_row.fee_structure_id
        return None

    fee_plan_id = pick_plan_id()
    fee_structure_id_resolved = pick_structure_id()
    plan = db.get(FeePlan, fee_plan_id) if fee_plan_id else None
    billed = effective_amount_paise(amount_paise, plan)

    installments = _installment_schedule(db, student_fee, plan, billed)
    next_due = _next_due_date(installments)

    return {
        "studentId": student_id,
        "sectionId": section_id,
        "amountPaise": billed,
        "baseAmountPaise": amount_paise,
        "feePlanId": fee_plan_id,
        "feeStructureId": fee_structure_id_resolved,
        "resolvedFrom": resolved_from,
        "orgNodeId": org_node_id,
        "orgNodeLabel": org_node_label,
        "feePlan": plan_to_dict(plan) if plan else None,
        "installments": installments,
        "nextDueDate": next_due.isoformat() if next_due else None,
    }


def _installment_schedule(
    db: Session, student_fee: StudentFee | None, plan: FeePlan | None, total_paise: int
) -> list[dict]:
    rows: list[tuple[int, date, int | None]] = []
    if student_fee:
        custom = list(
            db.scalars(
                select(StudentFeeInstallment)
                .where(StudentFeeInstallment.student_fee_id == student_fee.id)
                .order_by(StudentFeeInstallment.sequence)
            )
        )
        if custom:
            rows = [(r.sequence, r.due_date, r.amount_paise) for r in custom]
    if not rows and plan:
        plan_rows = list(
            db.scalars(
                select(FeePlanInstallment)
                .where(FeePlanInstallment.fee_plan_id == plan.id)
                .order_by(FeePlanInstallment.sequence)
            )
        )
        rows = [(r.sequence, r.due_date, r.amount_paise) for r in plan_rows]

    if not rows:
        return []

    specified = [a for _, _, a in rows if a is not None]
    unspecified_count = sum(1 for _, _, a in rows if a is None)
    remainder = total_paise - sum(specified)
    if unspecified_count > 0 and remainder > 0:
        each = remainder // unspecified_count
    else:
        each = 0

    out: list[dict] = []
    for seq, due, amt in rows:
        amount = amt if amt is not None else each
        out.append({"sequence": seq, "dueDate": due.isoformat(), "amountPaise": amount})
    return out


def _next_due_date(installments: list[dict]) -> date | None:
    today = date.today()
    for row in installments:
        due = date.fromisoformat(row["dueDate"])
        if due >= today:
            return due
    return date.fromisoformat(installments[-1]["dueDate"]) if installments else None


def resolved_from_label(code: str, org_node_label: str | None = None) -> str:
    if code == "org" and org_node_label:
        return org_node_label
    return {
        "student": "Student",
        "section": "Section",
        "class": "Class",
        "institute": "Institute",
        "org": org_node_label or "Organization",
        "none": "Not set",
    }.get(code, code)
