from __future__ import annotations

from app.services.keycloak_users import get_users_brief


def _empty_identity(user_id: str) -> dict:
    return {
        "firstName": "",
        "lastName": "",
        "displayName": "",
        "email": "",
        "username": "",
    }


def identity_for_user(user_id: str | None) -> dict:
    if not user_id:
        return _empty_identity("")
    briefs = get_users_brief([user_id])
    return briefs.get(user_id, _empty_identity(user_id))


def enrich_rows(rows: list[dict], *, id_key: str = "userId") -> list[dict]:
    ids = [row[id_key] for row in rows if row.get(id_key)]
    briefs = get_users_brief(ids)
    enriched: list[dict] = []
    for row in rows:
        item = dict(row)
        uid = item.get(id_key)
        if uid:
            item.update(briefs.get(uid, _empty_identity(uid)))
        enriched.append(item)
    return enriched
