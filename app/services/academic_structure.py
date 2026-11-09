from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import OrgNode, Section
import json

from app.services.institutes import require_membership, require_owner
from app.services.org_fee import (
    create_org_node,
    get_org_config,
    node_to_dict,
    sync_org_tree,
)


def _nest_nodes(flat: list[dict]) -> list[dict]:
    by_id = {n["id"]: {**n, "children": []} for n in flat}
    roots: list[dict] = []
    for node in flat:
        wrapped = by_id[node["id"]]
        pid = node.get("parentId")
        if pid and pid in by_id:
            by_id[pid]["children"].append(wrapped)
        elif node.get("level") == 0:
            roots.append(wrapped)
    for item in by_id.values():
        item["children"].sort(key=lambda c: (c["level"], c["label"]))
    return roots


def get_academic_tree(db: Session, institute_id: str, user_id: str) -> dict:
    require_membership(db, institute_id, user_id)
    sync_org_tree(db, institute_id)
    config = get_org_config(db, institute_id, user_id)
    rows = list(
        db.scalars(
            select(OrgNode)
            .where(OrgNode.institute_id == institute_id)
            .order_by(OrgNode.level, OrgNode.label)
        )
    )
    from app.services.org_fee import roster_org_level

    depth = config.get("enabledDepth", 4)
    labels = config.get("levelLabels") or []
    roster = roster_org_level(labels, depth)
    flat = [
        node_to_dict(n)
        for n in rows
        if n.level <= depth and (roster is None or n.level != roster)
    ]
    return {"config": config, "tree": _nest_nodes(flat)}


def create_academic_node(
    db: Session,
    institute_id: str,
    user_id: str,
    parent_id: str | None,
    level: int,
    label: str,
    description: str = "",
) -> dict:
    require_owner(db, institute_id, user_id)
    return create_org_node(
        db,
        institute_id,
        user_id,
        parent_id,
        level,
        label.strip(),
        description,
        academic=True,
    )


def create_section_under_class(
    db: Session,
    institute_id: str,
    user_id: str,
    parent_class_org_node_id: str,
    name: str,
    branch_id: str | None = None,
    description: str = "",
) -> dict:
    require_owner(db, institute_id, user_id)
    class_node = db.get(OrgNode, parent_class_org_node_id)
    if not class_node or class_node.institute_id != institute_id or class_node.level != 2:
        raise ValueError("Class node not found")
    clean_name = name.strip()
    if not clean_name:
        raise ValueError("Section name required")
    section = Section(
        institute_id=institute_id,
        name=clean_name,
        class_name=class_node.label,
        class_org_node_id=class_node.id,
        branch_id=branch_id,
    )
    db.add(section)
    db.commit()
    db.refresh(section)
    sync_org_tree(db, institute_id)
    sec_node = db.scalar(
        select(OrgNode).where(
            OrgNode.institute_id == institute_id,
            OrgNode.section_id == section.id,
            OrgNode.level == 3,
        )
    )
    if sec_node and description.strip():
        sec_node.description = description.strip()[:500]
        db.commit()
    return {
        "sectionId": section.id,
        "name": section.name,
        "className": section.class_name,
        "classOrgNodeId": section.class_org_node_id,
        "orgNodeId": sec_node.id if sec_node else None,
    }


def put_academic_org_config(
    db: Session, institute_id: str, user_id: str, enabled_depth: int, level_labels: list[dict]
) -> dict:
    from app.services.org_fee import (
        ORG_MAX_DEPTH,
        ORG_MIN_DEPTH,
        ensure_org_config,
        normalize_level_labels,
        org_config_to_dict,
    )

    require_owner(db, institute_id, user_id)
    if enabled_depth < ORG_MIN_DEPTH or enabled_depth > ORG_MAX_DEPTH:
        raise ValueError(f"enabledDepth must be {ORG_MIN_DEPTH}–{ORG_MAX_DEPTH}")
    row = ensure_org_config(db, institute_id)
    row.enabled_depth = enabled_depth
    row.level_labels_json = json.dumps(normalize_level_labels(enabled_depth, level_labels or []))
    db.commit()
    db.refresh(row)
    return org_config_to_dict(row)


def delete_academic_node(db: Session, institute_id: str, user_id: str, node_id: str) -> None:
    from app.services.sections import delete_section as remove_section

    require_owner(db, institute_id, user_id)
    node = db.get(OrgNode, node_id)
    if not node or node.institute_id != institute_id:
        raise ValueError("Node not found")
    if node.level == 0:
        raise ValueError("Cannot remove the institute root")
    if node.student_user_id:
        raise ValueError("Remove students from the class roster")
    child_count = db.scalar(
        select(OrgNode.id).where(OrgNode.parent_id == node_id, OrgNode.institute_id == institute_id).limit(1)
    )
    if child_count:
        raise ValueError("Remove child items first")
    if node.section_id:
        section_id = node.section_id
        remove_section(db, institute_id, section_id)
        stale = db.get(OrgNode, node_id)
        if stale:
            db.delete(stale)
        db.commit()
        sync_org_tree(db, institute_id)
        return
    db.delete(node)
    db.commit()
