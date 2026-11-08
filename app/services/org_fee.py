from __future__ import annotations

import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    ClassFeeDefault,
    Institute,
    InstituteFeeDefault,
    InstituteOrgConfig,
    OrgNode,
    OrgNodeFeeDefault,
    Section,
    SectionFeeDefault,
    SectionMember,
    StudentFee,
)
from app.services.fee_finance import plan_to_dict
from app.services.fees import _require_fee_manage
from app.services.institutes import require_membership

DEFAULT_LABELS: list[dict[str, Any]] = [
    {"level": 1, "label": "School band", "enabled": True},
    {"level": 2, "label": "Class", "enabled": True},
    {"level": 3, "label": "Section", "enabled": True},
    {"level": 4, "label": "Sub-section", "enabled": True},
    {"level": 5, "label": "Student", "enabled": False},
]


def _default_labels_json() -> str:
    return json.dumps(DEFAULT_LABELS)


def ensure_org_config(db: Session, institute_id: str) -> InstituteOrgConfig:
    row = db.get(InstituteOrgConfig, institute_id)
    if row:
        return row
    row = InstituteOrgConfig(
        institute_id=institute_id,
        enabled_depth=4,
        level_labels_json=_default_labels_json(),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def get_org_config(db: Session, institute_id: str, user_id: str) -> dict:
    require_membership(db, institute_id, user_id)
    row = ensure_org_config(db, institute_id)
    return org_config_to_dict(row)


def org_config_to_dict(row: InstituteOrgConfig) -> dict:
    try:
        labels = json.loads(row.level_labels_json or "[]")
    except json.JSONDecodeError:
        labels = DEFAULT_LABELS
    return {
        "instituteId": row.institute_id,
        "enabledDepth": row.enabled_depth,
        "levelLabels": labels,
    }


def put_org_config(
    db: Session, institute_id: str, user_id: str, enabled_depth: int, level_labels: list[dict]
) -> dict:
    _require_fee_manage(db, institute_id, user_id)
    if enabled_depth < 3 or enabled_depth > 5:
        raise ValueError("enabledDepth must be 3–5")
    row = ensure_org_config(db, institute_id)
    row.enabled_depth = enabled_depth
    if level_labels:
        row.level_labels_json = json.dumps(level_labels)
    db.commit()
    db.refresh(row)
    return org_config_to_dict(row)


def _find_root(db: Session, institute_id: str) -> OrgNode | None:
    return db.scalar(
        select(OrgNode).where(OrgNode.institute_id == institute_id, OrgNode.parent_id.is_(None), OrgNode.level == 0)
    )


def _find_or_create_class_node(
    db: Session, institute_id: str, parent_id: str, class_name: str, class_org_node_id: str | None = None
) -> OrgNode:
    if class_org_node_id:
        linked = db.get(OrgNode, class_org_node_id)
        if linked and linked.institute_id == institute_id and linked.level == 2:
            return linked
    label = (class_name or "Unassigned").strip() or "Unassigned"
    existing = db.scalar(
        select(OrgNode).where(
            OrgNode.institute_id == institute_id,
            OrgNode.parent_id == parent_id,
            OrgNode.level == 2,
            OrgNode.label == label,
        )
    )
    if existing:
        return existing
    node = OrgNode(institute_id=institute_id, parent_id=parent_id, level=2, label=label)
    db.add(node)
    db.flush()
    return node


def _find_section_node(db: Session, institute_id: str, section_id: str) -> OrgNode | None:
    return db.scalar(
        select(OrgNode).where(OrgNode.institute_id == institute_id, OrgNode.section_id == section_id, OrgNode.level == 3)
    )


def sync_org_tree(db: Session, institute_id: str) -> None:
    ensure_org_config(db, institute_id)
    institute = db.get(Institute, institute_id)
    if not institute:
        return
    root = _find_root(db, institute_id)
    if not root:
        root = OrgNode(
            institute_id=institute_id,
            parent_id=None,
            level=0,
            label=institute.name or "Institute",
        )
        db.add(root)
        db.flush()

    sections = list(db.scalars(select(Section).where(Section.institute_id == institute_id)))
    for section in sections:
        class_parent = root.id
        if section.class_org_node_id:
            band_parent = db.get(OrgNode, section.class_org_node_id)
            if band_parent and band_parent.level == 2:
                class_node = band_parent
            else:
                class_node = _find_or_create_class_node(
                    db, institute_id, class_parent, section.class_name or "", section.class_org_node_id
                )
        else:
            class_node = _find_or_create_class_node(db, institute_id, class_parent, section.class_name or "")
        sec_node = _find_section_node(db, institute_id, section.id)
        if not sec_node:
            sec_node = OrgNode(
                institute_id=institute_id,
                parent_id=class_node.id,
                level=3,
                label=section.name,
                section_id=section.id,
            )
            db.add(sec_node)
            db.flush()
        elif sec_node.parent_id != class_node.id:
            sec_node.parent_id = class_node.id

        student_ids = list(
            db.scalars(
                select(SectionMember.user_id).where(
                    SectionMember.section_id == section.id,
                    SectionMember.member_type == "student",
                )
            )
        )
        for student_id in student_ids:
            existing = db.scalar(
                select(OrgNode).where(
                    OrgNode.institute_id == institute_id,
                    OrgNode.level == 5,
                    OrgNode.student_user_id == student_id,
                    OrgNode.parent_id == sec_node.id,
                )
            )
            if not existing:
                db.add(
                    OrgNode(
                        institute_id=institute_id,
                        parent_id=sec_node.id,
                        level=5,
                        label=student_id[:8],
                        student_user_id=student_id,
                    )
                )

    db.commit()
    _backfill_node_defaults_from_ladder(db, institute_id)


def _copy_default(
    db: Session,
    institute_id: str,
    node_id: str,
    amount_paise: int,
    fee_plan_id: str | None,
    fee_structure_id: str | None,
) -> None:
    if amount_paise <= 0 and not fee_plan_id and not fee_structure_id:
        return
    row = db.get(OrgNodeFeeDefault, node_id)
    if row:
        if row.amount_paise > 0 or row.fee_plan_id or row.fee_structure_id:
            return
    else:
        row = OrgNodeFeeDefault(node_id=node_id, institute_id=institute_id)
        db.add(row)
    row.amount_paise = amount_paise
    row.fee_plan_id = fee_plan_id
    row.fee_structure_id = fee_structure_id


def _backfill_node_defaults_from_ladder(db: Session, institute_id: str) -> None:
    root = _find_root(db, institute_id)
    if not root:
        return
    inst = db.get(InstituteFeeDefault, institute_id)
    if inst:
        _copy_default(db, institute_id, root.id, inst.amount_paise, inst.fee_plan_id, inst.fee_structure_id)

    for class_row in db.scalars(select(ClassFeeDefault).where(ClassFeeDefault.institute_id == institute_id)):
        class_node = db.scalar(
            select(OrgNode).where(
                OrgNode.institute_id == institute_id,
                OrgNode.level == 2,
                OrgNode.label == class_row.class_name,
            )
        )
        if class_node:
            _copy_default(
                db,
                institute_id,
                class_node.id,
                class_row.amount_paise,
                class_row.fee_plan_id,
                class_row.fee_structure_id,
            )

    for sec_row in db.scalars(select(SectionFeeDefault).where(SectionFeeDefault.institute_id == institute_id)):
        sec_node = _find_section_node(db, institute_id, sec_row.section_id)
        if sec_node:
            _copy_default(
                db,
                institute_id,
                sec_node.id,
                sec_row.amount_paise,
                sec_row.fee_plan_id,
                sec_row.fee_structure_id,
            )

    for fee in db.scalars(select(StudentFee).where(StudentFee.institute_id == institute_id)):
        if not fee.section_id:
            continue
        sec_node = _find_section_node(db, institute_id, fee.section_id)
        if not sec_node:
            continue
        stu_node = db.scalar(
            select(OrgNode).where(
                OrgNode.institute_id == institute_id,
                OrgNode.parent_id == sec_node.id,
                OrgNode.student_user_id == fee.student_id,
                OrgNode.level == 5,
            )
        )
        if stu_node:
            _copy_default(
                db,
                institute_id,
                stu_node.id,
                fee.amount_paise,
                fee.fee_plan_id,
                fee.fee_structure_id,
            )
    db.commit()


def node_to_dict(node: OrgNode) -> dict:
    return {
        "id": node.id,
        "instituteId": node.institute_id,
        "parentId": node.parent_id,
        "level": node.level,
        "label": node.label,
        "sectionId": node.section_id,
        "studentUserId": node.student_user_id,
    }


def list_org_nodes_flat(db: Session, institute_id: str, user_id: str) -> list[dict]:
    require_membership(db, institute_id, user_id)
    sync_org_tree(db, institute_id)
    rows = list(
        db.scalars(select(OrgNode).where(OrgNode.institute_id == institute_id).order_by(OrgNode.level, OrgNode.label))
    )
    return [node_to_dict(n) for n in rows]


def _validate_org_parent(db: Session, institute_id: str, parent_id: str | None, level: int) -> None:
    if level == 1:
        root = _find_root(db, institute_id)
        if not root or parent_id != root.id:
            raise ValueError("School band must hang under the institute root")
        return
    if not parent_id:
        raise ValueError("parentId required")
    parent = db.get(OrgNode, parent_id)
    if not parent or parent.institute_id != institute_id:
        raise ValueError("Parent node not found")
    if level == 2 and parent.level not in {0, 1}:
        raise ValueError("Class must be under a school band or institute root")
    if level == 4 and parent.level != 3:
        raise ValueError("Sub-section must be under a section")


def create_org_node(
    db: Session,
    institute_id: str,
    user_id: str,
    parent_id: str | None,
    level: int,
    label: str,
    *,
    academic: bool = False,
) -> dict:
    if academic:
        from app.services.institutes import require_owner

        require_owner(db, institute_id, user_id)
    else:
        _require_fee_manage(db, institute_id, user_id)
    if level not in {1, 2, 4}:
        raise ValueError("Manual nodes allowed at levels 1 (band), 2 (class), or 4 (sub-section)")
    if level == 1:
        root = _find_root(db, institute_id)
        if not root:
            sync_org_tree(db, institute_id)
            root = _find_root(db, institute_id)
        parent_id = root.id if root else parent_id
    _validate_org_parent(db, institute_id, parent_id, level)
    node = OrgNode(
        institute_id=institute_id,
        parent_id=parent_id,
        level=level,
        label=label.strip()[:200],
    )
    db.add(node)
    db.commit()
    db.refresh(node)
    return node_to_dict(node)


def get_node_fee_default(db: Session, institute_id: str, user_id: str, node_id: str) -> dict:
    require_membership(db, institute_id, user_id)
    node = db.get(OrgNode, node_id)
    if not node or node.institute_id != institute_id:
        raise ValueError("Node not found")
    row = db.get(OrgNodeFeeDefault, node_id)
    from app.models import FeePlan

    plan = db.get(FeePlan, row.fee_plan_id) if row and row.fee_plan_id else None
    return {
        "nodeId": node_id,
        "amountPaise": row.amount_paise if row else 0,
        "feePlanId": row.fee_plan_id if row else None,
        "feeStructureId": row.fee_structure_id if row else None,
        "feePlan": plan_to_dict(plan, db=db) if plan else None,
    }


def put_node_fee_default(
    db: Session,
    institute_id: str,
    user_id: str,
    node_id: str,
    amount_paise: int,
    fee_plan_id: str | None,
    fee_structure_id: str | None,
) -> dict:
    _require_fee_manage(db, institute_id, user_id)
    node = db.get(OrgNode, node_id)
    if not node or node.institute_id != institute_id:
        raise ValueError("Node not found")
    row = db.get(OrgNodeFeeDefault, node_id)
    if not row:
        row = OrgNodeFeeDefault(node_id=node_id, institute_id=institute_id)
        db.add(row)
    row.amount_paise = max(amount_paise, 0)
    row.fee_plan_id = fee_plan_id
    row.fee_structure_id = fee_structure_id
    db.commit()
    return get_node_fee_default(db, institute_id, user_id, node_id)


def resolve_from_org_tree(
    db: Session, institute_id: str, section_id: str, student_id: str
) -> dict | None:
    sync_org_tree(db, institute_id)
    sec_node = _find_section_node(db, institute_id, section_id)
    if not sec_node:
        return None
    start = db.scalar(
        select(OrgNode).where(
            OrgNode.institute_id == institute_id,
            OrgNode.parent_id == sec_node.id,
            OrgNode.student_user_id == student_id,
            OrgNode.level == 5,
        )
    )
    if not start:
        start = sec_node

    chain: list[OrgNode] = []
    current: OrgNode | None = start
    while current:
        chain.append(current)
        current = db.get(OrgNode, current.parent_id) if current.parent_id else None

    for node in chain:
        row = db.get(OrgNodeFeeDefault, node.id)
        if not row:
            continue
        if row.amount_paise > 0 or row.fee_plan_id or row.fee_structure_id:
            label = (
                "student"
                if node.level == 5
                else "section"
                if node.level == 3
                else "class"
                if node.level == 2
                else "institute"
                if node.level == 0
                else "org"
            )
            return {
                "amountPaise": row.amount_paise,
                "feePlanId": row.fee_plan_id,
                "feeStructureId": row.fee_structure_id,
                "resolvedFrom": label,
                "orgNodeId": node.id,
                "orgNodeLabel": node.label,
            }
    return None
