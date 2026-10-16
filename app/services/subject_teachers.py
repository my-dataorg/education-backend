from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models import (
    Section,
    SectionMember,
    SectionSubject,
    Subject,
    TeacherSubjectAssignment,
)
from app.roles import TEACHING_STAFF_ROLES
from app.services.institutes import get_membership, list_members
from app.services.subjects import assign_teacher, link_subject
from app.services.user_identity import identity_for_user


def _sections(db: Session, institute_id: str, campus_id: str | None) -> list[Section]:
    sections = list(
        db.scalars(
            select(Section)
            .where(Section.institute_id == institute_id)
            .order_by(Section.class_name, Section.name)
        )
    )
    if not campus_id:
        return sections
    return [s for s in sections if s.branch_id == campus_id or s.branch_id is None]


def _section_label(section: Section) -> str:
    return f"{section.class_name or 'Class'} · {section.name}"


def _subjects(db: Session, institute_id: str) -> list[Subject]:
    return list(
        db.scalars(select(Subject).where(Subject.institute_id == institute_id).order_by(Subject.name))
    )


def _teacher_name(user_id: str) -> str:
    identity = identity_for_user(user_id)
    return identity.get("displayName") or identity.get("username") or user_id


def _columns_for_subjects(db: Session, sections: list[Section], subjects: list[Subject]) -> list[dict]:
    columns = []
    for subject in subjects:
        offered = []
        for section in sections:
            linked = db.scalar(
                select(SectionSubject).where(
                    SectionSubject.section_id == section.id,
                    SectionSubject.subject_id == subject.id,
                )
            )
            if linked:
                offered.append(_section_label(section))
        columns.append({"subjectId": subject.id, "name": subject.name, "offeredIn": offered})
    return columns


def get_subject_teacher_matrix(
    db: Session,
    institute_id: str,
    *,
    campus_id: str | None,
    show: str,
) -> dict:
    sections = _sections(db, institute_id, campus_id)
    subjects = _subjects(db, institute_id)
    columns = _columns_for_subjects(db, sections, subjects)

    if show == "teacher":
        staff = [
            m
            for m in list_members(db, institute_id, "staff")
            if m.role in TEACHING_STAFF_ROLES or m.role == "principal"
        ]
        rows = []
        for member in staff:
            cells = []
            for subject in subjects:
                section_labels = []
                for section in sections:
                    assigned = db.scalar(
                        select(TeacherSubjectAssignment).where(
                            TeacherSubjectAssignment.section_id == section.id,
                            TeacherSubjectAssignment.subject_id == subject.id,
                            TeacherSubjectAssignment.teacher_id == member.user_id,
                        )
                    )
                    if assigned:
                        section_labels.append(_section_label(section))
                cells.append(
                    {
                        "subjectId": subject.id,
                        "teacherId": member.user_id if section_labels else None,
                        "teacherName": _teacher_name(member.user_id) if section_labels else None,
                        "sectionLabels": section_labels or None,
                    }
                )
            rows.append(
                {
                    "teacherId": member.user_id,
                    "label": _teacher_name(member.user_id),
                    "cells": cells,
                }
            )
        return {"columns": columns, "rows": rows}

    rows = []
    for section in sections:
        cells = []
        for subject in subjects:
            teacher_id = db.scalar(
                select(TeacherSubjectAssignment.teacher_id).where(
                    TeacherSubjectAssignment.section_id == section.id,
                    TeacherSubjectAssignment.subject_id == subject.id,
                )
            )
            cells.append(
                {
                    "subjectId": subject.id,
                    "teacherId": teacher_id,
                    "teacherName": _teacher_name(teacher_id) if teacher_id else None,
                }
            )
        rows.append(
            {
                "sectionId": section.id,
                "classId": section.class_name,
                "label": _section_label(section),
                "cells": cells,
            }
        )
    return {"columns": columns, "rows": rows}


def list_subject_teacher_panel(db: Session, institute_id: str, *, campus_id: str | None) -> dict:
    sections = _sections(db, institute_id, campus_id)
    section_ids = {s.id for s in sections}
    staff = [
        m
        for m in list_members(db, institute_id, "staff")
        if m.role in TEACHING_STAFF_ROLES or m.role == "principal"
    ]
    items = []
    for member in staff:
        subject_map: dict[str, int] = {}
        class_teacher_of: list[str] = []
        for section in sections:
            sm = db.scalar(
                select(SectionMember).where(
                    SectionMember.section_id == section.id,
                    SectionMember.user_id == member.user_id,
                    SectionMember.member_type == "teacher",
                )
            )
            if sm and sm.member_type == "teacher":
                class_teacher_of.append(_section_label(section))
            for row in db.scalars(
                select(TeacherSubjectAssignment).where(
                    TeacherSubjectAssignment.section_id == section.id,
                    TeacherSubjectAssignment.teacher_id == member.user_id,
                )
            ):
                if row.section_id in section_ids:
                    subject_map[row.subject_id] = subject_map.get(row.subject_id, 0) + 1
        subjects = []
        for subject_id, count in subject_map.items():
            subject = db.get(Subject, subject_id)
            if subject:
                subjects.append({"subjectId": subject.id, "name": subject.name, "sectionsCount": count})
        items.append(
            {
                "personId": member.user_id,
                "name": _teacher_name(member.user_id),
                "subjects": subjects,
                "periodsPerWeek": sum(subject_map.values()),
                "weeklyLimit": 30,
                "classTeacherOf": class_teacher_of,
            }
        )
    return {"items": items}


def get_subject_teacher_checks(db: Session, institute_id: str, *, campus_id: str | None) -> dict:
    sections = _sections(db, institute_id, campus_id)
    unassigned_cells: list[dict] = []
    no_class_teachers: list[str] = []
    over_limit_teachers: list[str] = []

    for section in sections:
        for link in db.scalars(select(SectionSubject).where(SectionSubject.section_id == section.id)):
            teacher_id = db.scalar(
                select(TeacherSubjectAssignment.teacher_id).where(
                    TeacherSubjectAssignment.section_id == section.id,
                    TeacherSubjectAssignment.subject_id == link.subject_id,
                )
            )
            if not teacher_id:
                subject = db.get(Subject, link.subject_id)
                unassigned_cells.append(
                    {
                        "sectionId": section.id,
                        "sectionLabel": _section_label(section),
                        "subjectId": link.subject_id,
                        "subjectName": subject.name if subject else "",
                    }
                )
            elif teacher_id:
                enrolled = db.scalar(
                    select(SectionMember).where(
                        SectionMember.section_id == section.id,
                        SectionMember.user_id == teacher_id,
                        SectionMember.member_type == "teacher",
                    )
                )
                if not enrolled:
                    name = _teacher_name(teacher_id)
                    if name not in no_class_teachers:
                        no_class_teachers.append(name)

    panel = list_subject_teacher_panel(db, institute_id, campus_id=campus_id)
    for item in panel["items"]:
        if item["periodsPerWeek"] > item["weeklyLimit"]:
            over_limit_teachers.append(item["name"])

    return {
        "unassignedCount": len(unassigned_cells),
        "overLimitCount": len(over_limit_teachers),
        "noClassCount": len(no_class_teachers),
        "unassignedCells": unassigned_cells,
        "overLimitTeachers": over_limit_teachers,
        "noClassTeachers": no_class_teachers,
    }


def copy_subject_teachers(
    db: Session,
    institute_id: str,
    *,
    source_section_id: str,
    target_section_ids: list[str],
    replace_existing: bool,
) -> dict:
    source = db.get(Section, source_section_id)
    if not source or source.institute_id != institute_id:
        raise ValueError("Source section not found")
    assignments = list(
        db.scalars(
            select(TeacherSubjectAssignment).where(
                TeacherSubjectAssignment.section_id == source_section_id
            )
        )
    )
    changes: list[dict] = []
    for target_id in target_section_ids:
        target = db.get(Section, target_id)
        if not target or target.institute_id != institute_id:
            continue
        if replace_existing:
            db.execute(
                delete(TeacherSubjectAssignment).where(
                    TeacherSubjectAssignment.section_id == target_id
                )
            )
            db.commit()
        for row in assignments:
            link_subject(db, target_id, row.subject_id)
            membership = get_membership(db, institute_id, row.teacher_id)
            if not membership or membership.role not in TEACHING_STAFF_ROLES:
                continue
            existing = db.scalar(
                select(TeacherSubjectAssignment).where(
                    TeacherSubjectAssignment.section_id == target_id,
                    TeacherSubjectAssignment.subject_id == row.subject_id,
                    TeacherSubjectAssignment.teacher_id == row.teacher_id,
                )
            )
            if not existing:
                db.add(
                    TeacherSubjectAssignment(
                        section_id=target_id,
                        subject_id=row.subject_id,
                        teacher_id=row.teacher_id,
                    )
                )
                db.commit()
            changes.append(
                {
                    "targetSectionId": target_id,
                    "subjectId": row.subject_id,
                    "teacherId": row.teacher_id,
                }
            )
    return {"changes": changes, "changeCount": len(changes)}


def apply_subject_teacher_assignments(
    db: Session,
    institute_id: str,
    assignments: list[dict],
) -> None:
    for item in assignments:
        section_id = item["sectionId"]
        subject_id = item["subjectId"]
        teacher_id = item.get("teacherId")
        section = db.get(Section, section_id)
        if not section or section.institute_id != institute_id:
            raise ValueError("Section not found")
        link_subject(db, section_id, subject_id)
        db.execute(
            delete(TeacherSubjectAssignment).where(
                TeacherSubjectAssignment.section_id == section_id,
                TeacherSubjectAssignment.subject_id == subject_id,
            )
        )
        db.commit()
        if teacher_id:
            assign_teacher(db, section_id, subject_id, teacher_id)
