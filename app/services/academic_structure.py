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
    flat = [node_to_dict(n) for n in rows if n.level != 5]
    return {"config": config, "tree": _nest_nodes(flat)}


def create_academic_node(
    db: Session, institute_id: str, user_id: str, parent_id: str | None, level: int, label: str
) -> dict:
    require_owner(db, institute_id, user_id)
    return create_org_node(
        db, institute_id, user_id, parent_id, level, label.strip(), academic=True
    )


def create_section_under_class(
    db: Session,
    institute_id: str,
    user_id: str,
    parent_class_org_node_id: str,
    name: str,
    branch_id: str | None = None,
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
    from app.services.org_fee import ensure_org_config, org_config_to_dict

    require_owner(db, institute_id, user_id)
    if enabled_depth < 3 or enabled_depth > 5:
        raise ValueError("enabledDepth must be 3–5")
    row = ensure_org_config(db, institute_id)
    row.enabled_depth = enabled_depth
    if level_labels:
        row.level_labels_json = json.dumps(level_labels)
    db.commit()
    db.refresh(row)
    return org_config_to_dict(row)
