from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models import Section, SectionMember, SectionSubject, SectionSyllabusNode, Subject
from app.roles import MANAGE_ROLES, TEACHING_STAFF_ROLES
from app.services.institutes import get_membership, require_membership
from app.services.subjects import list_section_subjects

WEIGHT_TOLERANCE = 0.01
_UNSET = object()


def require_syllabus_admin(db: Session, institute_id: str, user_id: str) -> None:
    member = require_membership(db, institute_id, user_id)
    if member.role in MANAGE_ROLES or member.role == "principal":
        return
    raise PermissionError("Owner, admin, or principal role required")


def require_syllabus_completion_editor(db: Session, section_id: str, user_id: str) -> Section:
    section = db.get(Section, section_id)
    if not section:
        raise ValueError("Section not found")
    member = get_membership(db, section.institute_id, user_id)
    if not member or member.role not in TEACHING_STAFF_ROLES:
        raise PermissionError("Teaching staff required")
    enrolled = db.scalar(
        select(SectionMember).where(
            SectionMember.section_id == section_id,
            SectionMember.user_id == user_id,
            SectionMember.member_type == "teacher",
        )
    )
    if not enrolled:
        raise PermissionError("Must be assigned as teacher to this class")
    return section


def assert_subject_linked(db: Session, section_id: str, subject_id: str) -> Subject:
    link = db.scalar(
        select(SectionSubject).where(
            SectionSubject.section_id == section_id,
            SectionSubject.subject_id == subject_id,
        )
    )
    if not link:
        raise ValueError("Subject not linked to section")
    subject = db.get(Subject, subject_id)
    if not subject:
        raise ValueError("Subject not found")
    return subject


def _siblings_query(section_id: str, subject_id: str, parent_id: str | None):
    q = select(SectionSyllabusNode).where(
        SectionSyllabusNode.section_id == section_id,
        SectionSyllabusNode.subject_id == subject_id,
    )
    if parent_id is None:
        q = q.where(SectionSyllabusNode.parent_id.is_(None))
    else:
        q = q.where(SectionSyllabusNode.parent_id == parent_id)
    return q.order_by(SectionSyllabusNode.sort_order, SectionSyllabusNode.title)


def validate_sibling_weights(nodes: list[SectionSyllabusNode]) -> None:
    if not nodes:
        return
    total = sum(float(n.weight_percent) for n in nodes)
    if abs(total - 100.0) > WEIGHT_TOLERANCE:
        raise ValueError(f"Sibling weights must sum to 100 (currently {total:.2f})")


def _load_nodes(db: Session, section_id: str, subject_id: str) -> list[SectionSyllabusNode]:
    return list(
        db.scalars(
            select(SectionSyllabusNode)
            .where(
                SectionSyllabusNode.section_id == section_id,
                SectionSyllabusNode.subject_id == subject_id,
            )
            .order_by(SectionSyllabusNode.sort_order, SectionSyllabusNode.title)
        )
    )


def _effective_completed(
    node: SectionSyllabusNode, children_by_parent: dict[str | None, list[SectionSyllabusNode]]
) -> float:
    children = children_by_parent.get(node.id, [])
    if not children:
        return float(node.completed_percent or 0)
    return sum(float(c.weight_percent) * _effective_completed(c, children_by_parent) / 100.0 for c in children)


def _node_to_dict(
    node: SectionSyllabusNode,
    children_by_parent: dict[str | None, list[SectionSyllabusNode]],
    can_edit_completion: bool,
) -> dict:
    children = children_by_parent.get(node.id, [])
    is_leaf = len(children) == 0
    return {
        "id": node.id,
        "title": node.title,
        "weightPercent": float(node.weight_percent),
        "sortOrder": node.sort_order,
        "completedPercent": float(node.completed_percent or 0),
        "effectiveCompletedPercent": round(_effective_completed(node, children_by_parent), 2),
        "isLeaf": is_leaf,
        "canEditCompletion": can_edit_completion and is_leaf,
        "children": [
            _node_to_dict(child, children_by_parent, can_edit_completion)
            for child in sorted(children, key=lambda n: (n.sort_order, n.title))
        ],
    }


def _subject_total(
    roots: list[SectionSyllabusNode], children_by_parent: dict[str | None, list[SectionSyllabusNode]]
) -> float:
    if not roots:
        return 0.0
    return round(
        sum(float(r.weight_percent) * _effective_completed(r, children_by_parent) / 100.0 for r in roots),
        2,
    )


def _children_map(nodes: list[SectionSyllabusNode]) -> dict[str | None, list[SectionSyllabusNode]]:
    by_parent: dict[str | None, list[SectionSyllabusNode]] = defaultdict(list)
    for node in nodes:
        by_parent[node.parent_id].append(node)
    return by_parent


def build_tree(db: Session, section_id: str, subject_id: str, can_edit_completion: bool) -> dict:
    subject = assert_subject_linked(db, section_id, subject_id)
    nodes = _load_nodes(db, section_id, subject_id)
    by_parent = _children_map(nodes)
    roots = sorted(by_parent.get(None, []), key=lambda n: (n.sort_order, n.title))
    return {
        "subjectId": subject.id,
        "subjectName": subject.name,
        "subjectTotalCompletedPercent": _subject_total(roots, by_parent),
        "nodes": [_node_to_dict(r, by_parent, can_edit_completion) for r in roots],
    }


def list_syllabus_summaries(db: Session, section_id: str) -> list[dict]:
    rows = list_section_subjects(db, section_id)
    summaries = []
    for row in rows:
        subject_id = row["id"]
        nodes = _load_nodes(db, section_id, subject_id)
        by_parent = _children_map(nodes)
        roots = by_parent.get(None, [])
        summaries.append(
            {
                "subjectId": subject_id,
                "subjectName": row["name"],
                "totalCompletedPercent": _subject_total(roots, by_parent),
                "nodeCount": len(nodes),
            }
        )
    return summaries


def _validate_parent(db: Session, section_id: str, subject_id: str, parent_id: str | None) -> None:
    if not parent_id:
        return
    parent = db.get(SectionSyllabusNode, parent_id)
    if not parent or parent.section_id != section_id or parent.subject_id != subject_id:
        raise ValueError("Parent node not found")


def create_node(
    db: Session,
    section_id: str,
    subject_id: str,
    title: str,
    weight_percent: float,
    parent_id: str | None = None,
    sort_order: int | None = None,
) -> SectionSyllabusNode:
    assert_subject_linked(db, section_id, subject_id)
    _validate_parent(db, section_id, subject_id, parent_id)
    if weight_percent <= 0 or weight_percent > 100:
        raise ValueError("weightPercent must be between 0 and 100")
    if sort_order is None:
        siblings = list(db.scalars(_siblings_query(section_id, subject_id, parent_id)))
        sort_order = len(siblings)
    node = SectionSyllabusNode(
        section_id=section_id,
        subject_id=subject_id,
        parent_id=parent_id,
        title=title.strip(),
        weight_percent=weight_percent,
        sort_order=sort_order,
    )
    db.add(node)
    db.flush()
    siblings = list(db.scalars(_siblings_query(section_id, subject_id, parent_id)))
    validate_sibling_weights(siblings)
    db.commit()
    db.refresh(node)
    return node


def _would_create_cycle(db: Session, node_id: str, new_parent_id: str) -> bool:
    current = db.get(SectionSyllabusNode, new_parent_id)
    while current:
        if current.id == node_id:
            return True
        if not current.parent_id:
            break
        current = db.get(SectionSyllabusNode, current.parent_id)
    return False


def update_node(
    db: Session,
    section_id: str,
    subject_id: str,
    node_id: str,
    *,
    title: str | None = None,
    weight_percent: float | None = None,
    parent_id: str | None | object = _UNSET,
    sort_order: int | None = None,
) -> SectionSyllabusNode:
    node = db.get(SectionSyllabusNode, node_id)
    if not node or node.section_id != section_id or node.subject_id != subject_id:
        raise ValueError("Node not found")
    if parent_id is not _UNSET:
        new_parent = parent_id
        if new_parent == node_id:
            raise ValueError("Node cannot be its own parent")
        if new_parent and _would_create_cycle(db, node_id, new_parent):
            raise ValueError("Cannot move node under its descendant")
        _validate_parent(db, section_id, subject_id, new_parent)
        node.parent_id = new_parent
    if title is not None:
        node.title = title.strip()
    if weight_percent is not None:
        if weight_percent <= 0 or weight_percent > 100:
            raise ValueError("weightPercent must be between 0 and 100")
        node.weight_percent = weight_percent
    if sort_order is not None:
        node.sort_order = sort_order
    db.flush()
    siblings = list(db.scalars(_siblings_query(section_id, subject_id, node.parent_id)))
    validate_sibling_weights(siblings)
    db.commit()
    db.refresh(node)
    return node


def delete_node(db: Session, section_id: str, subject_id: str, node_id: str) -> None:
    node = db.get(SectionSyllabusNode, node_id)
    if not node or node.section_id != section_id or node.subject_id != subject_id:
        raise ValueError("Node not found")
    db.execute(delete(SectionSyllabusNode).where(SectionSyllabusNode.id == node_id))
    db.commit()


def _clone_subject_syllabus(
    db: Session,
    source_section_id: str,
    target_section_id: str,
    subject_id: str,
) -> int:
    nodes = _load_nodes(db, source_section_id, subject_id)
    if not nodes:
        return 0
    assert_subject_linked(db, target_section_id, subject_id)
    db.execute(
        delete(SectionSyllabusNode).where(
            SectionSyllabusNode.section_id == target_section_id,
            SectionSyllabusNode.subject_id == subject_id,
        )
    )
    by_parent = _children_map(nodes)

    def clone_children(parent_old_id: str | None, parent_new_id: str | None) -> None:
        children = sorted(
            by_parent.get(parent_old_id, []), key=lambda n: (n.sort_order, n.title)
        )
        for old in children:
            new = SectionSyllabusNode(
                section_id=target_section_id,
                subject_id=subject_id,
                parent_id=parent_new_id,
                title=old.title,
                weight_percent=old.weight_percent,
                sort_order=old.sort_order,
                completed_percent=0,
            )
            db.add(new)
            db.flush()
            clone_children(old.id, new.id)

    clone_children(None, None)
    return len(nodes)


def copy_syllabus_between_sections(
    db: Session,
    institute_id: str,
    source_section_id: str,
    target_section_ids: list[str],
) -> dict:
    source = db.get(Section, source_section_id)
    if not source or source.institute_id != institute_id:
        raise ValueError("Source section not found")
    if not target_section_ids:
        raise ValueError("targetSectionIds required")
    if source_section_id in target_section_ids:
        raise ValueError("Cannot copy a section to itself")

    source_subject_ids = {row["id"] for row in list_section_subjects(db, source_section_id)}
    subjects_copied = 0
    node_count = 0

    for target_id in target_section_ids:
        target = db.get(Section, target_id)
        if not target or target.institute_id != institute_id:
            raise ValueError("Target section not found")
        target_subject_ids = {row["id"] for row in list_section_subjects(db, target_id)}
        for subject_id in source_subject_ids & target_subject_ids:
            copied = _clone_subject_syllabus(db, source_section_id, target_id, subject_id)
            if copied:
                subjects_copied += 1
                node_count += copied

    db.commit()
    return {
        "subjectsCopied": subjects_copied,
        "nodesCopied": node_count,
        "targetCount": len(target_section_ids),
    }


def set_leaf_completion(
    db: Session,
    section_id: str,
    subject_id: str,
    node_id: str,
    completed_percent: float,
    user_id: str,
) -> dict:
    if completed_percent < 0 or completed_percent > 100:
        raise ValueError("completedPercent must be between 0 and 100")
    node = db.get(SectionSyllabusNode, node_id)
    if not node or node.section_id != section_id or node.subject_id != subject_id:
        raise ValueError("Node not found")
    has_child = db.scalar(
        select(SectionSyllabusNode.id).where(SectionSyllabusNode.parent_id == node_id).limit(1)
    )
    if has_child:
        raise ValueError("Completion can only be set on leaf nodes")
    node.completed_percent = completed_percent
    node.completed_by_user_id = user_id
    node.completed_at = datetime.now(timezone.utc)
    db.commit()
    return build_tree(db, section_id, subject_id, can_edit_completion=True)
