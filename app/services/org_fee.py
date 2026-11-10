from __future__ import annotations

import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    ClassFeeDefault,
    FeePlan,
    FeeStructure,
    Institute,
    InstituteFeeDefault,
    InstituteOrgConfig,
    OrgNode,
    OrgNodeFeeDefault,
    OrgNodeFeeItem,
    Section,
    SectionFeeDefault,
    SectionMember,
    StudentFee,
)
from app.services.fee_finance import plan_to_dict
from app.services.fees import _require_fee_manage
from app.services.institutes import require_membership

ORG_MIN_DEPTH = 3
ORG_MAX_DEPTH = 20
CLASS_ORG_LEVEL = 2
SECTION_ORG_LEVEL = 3

DEFAULT_LABELS: list[dict[str, Any]] = [
    {"level": 1, "label": "School band", "enabled": True, "role": "org"},
    {"level": 2, "label": "Class", "enabled": True, "role": "class"},
    {"level": 3, "label": "Section", "enabled": True, "role": "section"},
    {"level": 4, "label": "Sub-section", "enabled": True, "role": "org"},
    {"level": 5, "label": "Student", "enabled": False, "role": "roster"},
]


def _labels_from_config(row: InstituteOrgConfig) -> list[dict[str, Any]]:
    try:
        labels = json.loads(row.level_labels_json or "[]")
    except json.JSONDecodeError:
        labels = list(DEFAULT_LABELS)
    return labels if isinstance(labels, list) else list(DEFAULT_LABELS)


def roster_org_level(labels: list[dict[str, Any]], enabled_depth: int) -> int | None:
    for item in labels:
        if item.get("level") == enabled_depth and item.get("enabled") and item.get("role") == "roster":
            return enabled_depth
    for item in labels:
        if item.get("level") == enabled_depth and item.get("enabled"):
            if "student" in str(item.get("label", "")).lower():
                return enabled_depth
    if enabled_depth >= 5:
        for item in labels:
            if item.get("level") == 5 and item.get("enabled") and "student" in str(item.get("label", "")).lower():
                return 5
    return None


def normalize_level_labels(enabled_depth: int, level_labels: list[dict]) -> list[dict[str, Any]]:
    by_level = {int(l["level"]): l for l in level_labels if "level" in l}
    out: list[dict[str, Any]] = []
    for lvl in range(1, enabled_depth + 1):
        prev = by_level.get(lvl, {})
        if lvl == CLASS_ORG_LEVEL:
            out.append(
                {
                    "level": lvl,
                    "label": (prev.get("label") or "Class").strip()[:80] or "Class",
                    "enabled": True,
                    "role": "class",
                }
            )
        elif lvl == SECTION_ORG_LEVEL:
            out.append(
                {
                    "level": lvl,
                    "label": (prev.get("label") or "Section").strip()[:80] or "Section",
                    "enabled": True,
                    "role": "section",
                }
            )
        elif prev.get("role") == "roster" and lvl == enabled_depth:
            out.append(
                {
                    "level": lvl,
                    "label": (prev.get("label") or "Student").strip()[:80] or "Student",
                    "enabled": bool(prev.get("enabled", True)),
                    "role": "roster",
                }
            )
        elif prev:
            out.append(
                {
                    "level": lvl,
                    "label": str(prev.get("label", f"Level {lvl}")).strip()[:80] or f"Level {lvl}",
                    "enabled": bool(prev.get("enabled", True)),
                    "role": str(prev.get("role") or "org"),
                }
            )
        else:
            out.append({"level": lvl, "label": f"Level {lvl}", "enabled": True, "role": "org"})
    return out


def manual_org_levels(enabled_depth: int, labels: list[dict[str, Any]]) -> set[int]:
    roster = roster_org_level(labels, enabled_depth)
    levels = set(range(1, enabled_depth + 1))
    levels.discard(SECTION_ORG_LEVEL)
    if roster is not None:
        levels.discard(roster)
    return levels


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
    if enabled_depth < ORG_MIN_DEPTH or enabled_depth > ORG_MAX_DEPTH:
        raise ValueError(f"enabledDepth must be {ORG_MIN_DEPTH}–{ORG_MAX_DEPTH}")
    row = ensure_org_config(db, institute_id)
    row.enabled_depth = enabled_depth
    normalized = normalize_level_labels(enabled_depth, level_labels or [])
    row.level_labels_json = json.dumps(normalized)
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
        cfg = ensure_org_config(db, institute_id)
        label_rows = _labels_from_config(cfg)
        student_level = roster_org_level(label_rows, cfg.enabled_depth)
        if student_level is not None:
            for student_id in student_ids:
                existing = db.scalar(
                    select(OrgNode).where(
                        OrgNode.institute_id == institute_id,
                        OrgNode.level == student_level,
                        OrgNode.student_user_id == student_id,
                        OrgNode.parent_id == sec_node.id,
                    )
                )
                if not existing:
                    db.add(
                        OrgNode(
                            institute_id=institute_id,
                            parent_id=sec_node.id,
                            level=student_level,
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
    if fee_structure_id:
        item = db.get(OrgNodeFeeItem, (node_id, fee_structure_id))
        if not item:
            item = OrgNodeFeeItem(
                node_id=node_id,
                fee_structure_id=fee_structure_id,
                institute_id=institute_id,
            )
            db.add(item)
        item.amount_paise = amount_paise
        item.fee_plan_id = fee_plan_id


def _sync_legacy_default_from_items(db: Session, institute_id: str, node_id: str) -> None:
    items = list(
        db.scalars(
            select(OrgNodeFeeItem)
            .where(OrgNodeFeeItem.node_id == node_id)
            .order_by(OrgNodeFeeItem.fee_structure_id)
        )
    )
    row = db.get(OrgNodeFeeDefault, node_id)
    if not items:
        return
    primary = items[0]
    if not row:
        row = OrgNodeFeeDefault(node_id=node_id, institute_id=institute_id)
        db.add(row)
    row.amount_paise = primary.amount_paise
    row.fee_plan_id = primary.fee_plan_id
    row.fee_structure_id = primary.fee_structure_id


def _node_resolved_label(node: OrgNode) -> str:
    if node.student_user_id:
        return "student"
    if node.level == SECTION_ORG_LEVEL:
        return "section"
    if node.level == CLASS_ORG_LEVEL:
        return "class"
    if node.level == 0:
        return "institute"
    return "org"


def _build_org_chain(
    db: Session, institute_id: str, section_id: str, student_id: str
) -> list[OrgNode]:
    sync_org_tree(db, institute_id)
    sec_node = _find_section_node(db, institute_id, section_id)
    if not sec_node:
        return []
    start = db.scalar(
        select(OrgNode).where(
            OrgNode.institute_id == institute_id,
            OrgNode.parent_id == sec_node.id,
            OrgNode.student_user_id == student_id,
        )
    )
    if not start:
        start = sec_node
    chain: list[OrgNode] = []
    current: OrgNode | None = start
    while current:
        chain.append(current)
        current = db.get(OrgNode, current.parent_id) if current.parent_id else None
    return chain


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
        "description": node.description or "",
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
    if level == CLASS_ORG_LEVEL:
        if not parent_id:
            raise ValueError("parentId required")
        parent = db.get(OrgNode, parent_id)
        if not parent or parent.institute_id != institute_id:
            raise ValueError("Parent node not found")
        if parent.level not in {0, 1}:
            raise ValueError("Class must be under a school band or institute root")
        return
    if level == 1:
        root = _find_root(db, institute_id)
        if not root or parent_id != root.id:
            raise ValueError("Top tier must hang under the institute root")
        return
    if level == SECTION_ORG_LEVEL:
        raise ValueError("Use the sections API for section nodes")
    if not parent_id:
        raise ValueError("parentId required")
    parent = db.get(OrgNode, parent_id)
    if not parent or parent.institute_id != institute_id:
        raise ValueError("Parent node not found")
    if parent.level + 1 != level:
        raise ValueError("Parent must be exactly one level above")


def create_org_node(
    db: Session,
    institute_id: str,
    user_id: str,
    parent_id: str | None,
    level: int,
    label: str,
    description: str = "",
    *,
    academic: bool = False,
) -> dict:
    if academic:
        from app.services.institutes import require_owner

        require_owner(db, institute_id, user_id)
    else:
        _require_fee_manage(db, institute_id, user_id)
    cfg = ensure_org_config(db, institute_id)
    label_rows = _labels_from_config(cfg)
    if level == SECTION_ORG_LEVEL:
        raise ValueError("Use the sections API for section nodes")
    roster = roster_org_level(label_rows, cfg.enabled_depth)
    if roster is not None and level == roster:
        raise ValueError("Roster level is synced from class enrollment")
    allowed = manual_org_levels(cfg.enabled_depth, label_rows)
    if level not in allowed:
        raise ValueError(f"Level {level} is not configured for manual org nodes")
    if level > cfg.enabled_depth:
        raise ValueError("Level exceeds configured hierarchy depth")
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
        description=(description or "").strip()[:500],
    )
    db.add(node)
    db.commit()
    db.refresh(node)
    return node_to_dict(node)


def list_node_fee_items(db: Session, institute_id: str, user_id: str, node_id: str) -> list[dict]:
    require_membership(db, institute_id, user_id)
    node = db.get(OrgNode, node_id)
    if not node or node.institute_id != institute_id:
        raise ValueError("Node not found")
    rows = list(
        db.scalars(
            select(OrgNodeFeeItem)
            .where(OrgNodeFeeItem.node_id == node_id)
            .order_by(OrgNodeFeeItem.fee_structure_id)
        )
    )
    out: list[dict] = []
    for item in rows:
        struct = db.get(FeeStructure, item.fee_structure_id)
        plan = db.get(FeePlan, item.fee_plan_id) if item.fee_plan_id else None
        out.append(
            {
                "nodeId": node_id,
                "feeStructureId": item.fee_structure_id,
                "feeStructureName": struct.name if struct else "",
                "amountPaise": item.amount_paise,
                "feePlanId": item.fee_plan_id,
                "feePlan": plan_to_dict(plan, db=db) if plan else None,
            }
        )
    return out


def put_node_fee_items(
    db: Session, institute_id: str, user_id: str, node_id: str, items: list[dict]
) -> list[dict]:
    _require_fee_manage(db, institute_id, user_id)
    node = db.get(OrgNode, node_id)
    if not node or node.institute_id != institute_id:
        raise ValueError("Node not found")
    for row in db.scalars(select(OrgNodeFeeItem).where(OrgNodeFeeItem.node_id == node_id)):
        db.delete(row)
    for raw in items:
        fs_id = raw.get("feeStructureId") or raw.get("fee_structure_id")
        if not fs_id:
            continue
        structure = db.get(FeeStructure, fs_id)
        if not structure or structure.institute_id != institute_id:
            raise ValueError("Fee structure not found")
        amount = int(raw.get("amountPaise") or raw.get("amount_paise") or 0)
        plan_id = raw.get("feePlanId") or raw.get("fee_plan_id")
        db.add(
            OrgNodeFeeItem(
                node_id=node_id,
                fee_structure_id=fs_id,
                institute_id=institute_id,
                amount_paise=max(amount, 0),
                fee_plan_id=plan_id,
            )
        )
    db.flush()
    _sync_legacy_default_from_items(db, institute_id, node_id)
    db.commit()
    return list_node_fee_items(db, institute_id, user_id, node_id)


def get_node_fee_default(db: Session, institute_id: str, user_id: str, node_id: str) -> dict:
    require_membership(db, institute_id, user_id)
    node = db.get(OrgNode, node_id)
    if not node or node.institute_id != institute_id:
        raise ValueError("Node not found")
    items = list_node_fee_items(db, institute_id, user_id, node_id)
    if items:
        first = items[0]
        return {
            "nodeId": node_id,
            "amountPaise": first["amountPaise"],
            "feePlanId": first["feePlanId"],
            "feeStructureId": first["feeStructureId"],
            "feePlan": first.get("feePlan"),
        }
    row = db.get(OrgNodeFeeDefault, node_id)
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
    if fee_structure_id:
        item = db.get(OrgNodeFeeItem, (node_id, fee_structure_id))
        if not item:
            item = OrgNodeFeeItem(
                node_id=node_id,
                fee_structure_id=fee_structure_id,
                institute_id=institute_id,
            )
            db.add(item)
        item.amount_paise = max(amount_paise, 0)
        item.fee_plan_id = fee_plan_id
    db.commit()
    return get_node_fee_default(db, institute_id, user_id, node_id)


def resolve_org_fee_lines(
    db: Session, institute_id: str, section_id: str, student_id: str
) -> list[dict]:
    chain = _build_org_chain(db, institute_id, section_id, student_id)
    if not chain:
        return []
    picked: dict[str, tuple[OrgNodeFeeItem, OrgNode]] = {}
    for node in chain:
        items = list(
            db.scalars(select(OrgNodeFeeItem).where(OrgNodeFeeItem.node_id == node.id))
        )
        for item in items:
            if item.amount_paise <= 0 and not item.fee_plan_id:
                continue
            if item.fee_structure_id not in picked:
                picked[item.fee_structure_id] = (item, node)
    lines: list[dict] = []
    for fee_structure_id, (item, node) in picked.items():
        struct = db.get(FeeStructure, fee_structure_id)
        lines.append(
            {
                "feeStructureId": fee_structure_id,
                "feeStructureName": struct.name if struct else "",
                "amountPaise": item.amount_paise,
                "feePlanId": item.fee_plan_id,
                "resolvedFrom": _node_resolved_label(node),
                "orgNodeId": node.id,
                "orgNodeLabel": node.label,
            }
        )
    lines.sort(key=lambda x: x["feeStructureName"])
    return lines


def resolve_from_org_tree(
    db: Session, institute_id: str, section_id: str, student_id: str
) -> dict | None:
    lines = resolve_org_fee_lines(db, institute_id, section_id, student_id)
    if lines:
        line = lines[0]
        return {
            "amountPaise": line["amountPaise"],
            "feePlanId": line["feePlanId"],
            "feeStructureId": line["feeStructureId"],
            "resolvedFrom": line["resolvedFrom"],
            "orgNodeId": line["orgNodeId"],
            "orgNodeLabel": line["orgNodeLabel"],
        }
    chain = _build_org_chain(db, institute_id, section_id, student_id)
    for node in chain:
        row = db.get(OrgNodeFeeDefault, node.id)
        if row and row.amount_paise > 0:
            return {
                "amountPaise": row.amount_paise,
                "feePlanId": row.fee_plan_id,
                "feeStructureId": row.fee_structure_id,
                "resolvedFrom": _node_resolved_label(node),
                "orgNodeId": node.id,
                "orgNodeLabel": node.label,
            }
    return None
