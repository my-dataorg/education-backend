import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import NoticeDistributionList
from app.services.institutes import require_manage, require_membership

def parse_id_list(raw: str) -> list[str]:
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, list):
            return [str(x) for x in parsed if x]
    except json.JSONDecodeError:
        pass
    return [part for part in raw.split(",") if part]


def serialize_id_list(ids: list[str]) -> str:
    return json.dumps(ids) if ids else ""



def list_distribution_lists(db: Session, institute_id: str, user_id: str) -> list[NoticeDistributionList]:
    require_membership(db, institute_id, user_id)
    return list(
        db.scalars(
            select(NoticeDistributionList)
            .where(NoticeDistributionList.institute_id == institute_id)
            .order_by(NoticeDistributionList.name)
        )
    )


def create_distribution_list(
    db: Session,
    institute_id: str,
    user_id: str,
    name: str,
    audience: str,
    target_section_ids: list[str],
    target_user_ids: list[str],
    student_gender: str | None,
) -> NoticeDistributionList:
    require_manage(db, institute_id, user_id)
    row = NoticeDistributionList(
        institute_id=institute_id,
        name=name.strip(),
        audience=audience,
        target_section_ids=serialize_id_list(target_section_ids),
        target_user_ids=serialize_id_list(target_user_ids),
        student_gender=student_gender,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def delete_distribution_list(db: Session, institute_id: str, user_id: str, list_id: str) -> None:
    require_manage(db, institute_id, user_id)
    row = db.get(NoticeDistributionList, list_id)
    if not row or row.institute_id != institute_id:
        raise ValueError("Distribution list not found")
    db.delete(row)
    db.commit()


def get_distribution_list(db: Session, institute_id: str, list_id: str) -> NoticeDistributionList | None:
    row = db.get(NoticeDistributionList, list_id)
    if not row or row.institute_id != institute_id:
        return None
    return row


def distribution_list_to_dict(row: NoticeDistributionList) -> dict:
    return {
        "id": row.id,
        "name": row.name,
        "audience": row.audience,
        "targetSectionIds": parse_id_list(row.target_section_ids),
        "targetUserIds": parse_id_list(row.target_user_ids),
        "studentGender": row.student_gender,
        "createdAt": row.created_at,
    }
