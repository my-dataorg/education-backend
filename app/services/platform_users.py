from app.platform_client import platform_get


def _item_to_search(item: dict) -> dict:
    username = (item.get("username") or "").strip()
    email = (item.get("email") or "").strip().lower()
    name = (item.get("name") or "").strip()
    return {
        "userId": item.get("id") or "",
        "email": email,
        "username": username,
        "displayName": name or username or email,
    }


def _item_to_brief(item: dict) -> dict:
    return {
        "firstName": (item.get("firstName") or "").strip(),
        "lastName": (item.get("lastName") or "").strip(),
        "displayName": (item.get("name") or "").strip(),
        "email": (item.get("email") or "").strip().lower(),
        "username": (item.get("username") or "").strip(),
    }


def search_users(query: str, *, limit: int = 10) -> list[dict]:
    q = query.strip()
    if len(q) < 2:
        return []
    data = platform_get("/internal/users/search", {"q": q, "limit": limit})
    if not data:
        return []
    results = []
    for item in data.get("items", []):
        row = _item_to_search(item)
        if row["userId"] and (row["email"] or row["username"]):
            results.append(row)
    return results[:limit]


def get_users_brief(user_ids: list[str]) -> dict[str, dict]:
    unique = list(dict.fromkeys(uid for uid in user_ids if uid))
    if not unique:
        return {}
    data = platform_get("/internal/users/briefs", {"ids": ",".join(unique)})
    if not data:
        return {}
    result: dict[str, dict] = {}
    for item in data.get("items", []):
        uid = item.get("id")
        if uid:
            result[uid] = _item_to_brief(item)
    return result


def find_user_id_by_email(email: str) -> str | None:
    normalized = email.strip().lower()
    if not normalized or "@" not in normalized:
        return None
    rows = search_users(normalized, limit=5)
    for row in rows:
        if row["email"] == normalized:
            return row["userId"]
    return None
