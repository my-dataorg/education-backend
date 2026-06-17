import time

import httpx

from app.config import settings

_admin_token: str | None = None
_admin_token_expires: float = 0


async def _fetch_admin_token() -> str:
    global _admin_token, _admin_token_expires
    if _admin_token and time.time() < _admin_token_expires - 30:
        return _admin_token

    async with httpx.AsyncClient() as client:
        res = await client.post(
            f"{settings.keycloak_url}/realms/master/protocol/openid-connect/token",
            data={
                "grant_type": "password",
                "client_id": "admin-cli",
                "username": settings.keycloak_admin_user,
                "password": settings.keycloak_admin_password,
            },
            timeout=10,
        )
        res.raise_for_status()
        data = res.json()
        _admin_token = data["access_token"]
        _admin_token_expires = time.time() + int(data.get("expires_in", 60))
        return _admin_token


def _display_name(user: dict) -> str:
    first = (user.get("firstName") or "").strip()
    last = (user.get("lastName") or "").strip()
    name = f"{first} {last}".strip()
    if name:
        return name
    if user.get("name"):
        return str(user["name"])
    return user.get("username") or user.get("email") or ""


def _resolve_email(user: dict) -> str:
    email = user.get("email") or ""
    if isinstance(email, str) and "@" in email:
        return email.strip().lower()
    username = user.get("username") or ""
    if isinstance(username, str) and "@" in username:
        return username.strip().lower()
    return ""


async def search_users(query: str, *, limit: int = 10) -> list[dict]:
    q = query.strip()
    if len(q) < 2:
        return []

    try:
        token = await _fetch_admin_token()
        async with httpx.AsyncClient() as client:
            res = await client.get(
                f"{settings.keycloak_url}/admin/realms/{settings.keycloak_realm}/users",
                params={"search": q, "max": limit},
                headers={"Authorization": f"Bearer {token}"},
                timeout=10,
            )
            if res.status_code != 200:
                return []
            users = res.json()
    except httpx.HTTPError:
        return []

    results: list[dict] = []
    for user in users:
        if user.get("enabled") is False:
            continue
        user_id = user.get("id")
        if not user_id:
            continue
        username = (user.get("username") or "").strip()
        email = _resolve_email(user)
        display = _display_name(user)
        if not email and not username:
            continue
        results.append(
            {
                "userId": user_id,
                "email": email,
                "username": username,
                "displayName": display or username or email,
            }
        )
    return results[:limit]


_brief_cache: dict[str, tuple[float, dict]] = {}
_BRIEF_CACHE_TTL = 300


def _user_to_brief(user: dict) -> dict:
    user_id = user.get("id") or ""
    first = (user.get("firstName") or "").strip()
    last = (user.get("lastName") or "").strip()
    return {
        "firstName": first,
        "lastName": last,
        "displayName": _display_name(user),
        "email": _resolve_email(user),
        "username": (user.get("username") or "").strip(),
    }


def _fetch_admin_token_sync(client: httpx.Client) -> str | None:
    try:
        token_res = client.post(
            f"{settings.keycloak_url}/realms/master/protocol/openid-connect/token",
            data={
                "grant_type": "password",
                "client_id": "admin-cli",
                "username": settings.keycloak_admin_user,
                "password": settings.keycloak_admin_password,
            },
        )
        token_res.raise_for_status()
        return token_res.json()["access_token"]
    except httpx.HTTPError:
        return None


def get_users_brief(user_ids: list[str]) -> dict[str, dict]:
    unique = list(dict.fromkeys(uid for uid in user_ids if uid))
    if not unique:
        return {}

    now = time.time()
    result: dict[str, dict] = {}
    missing: list[str] = []
    for uid in unique:
        cached = _brief_cache.get(uid)
        if cached and now < cached[0]:
            result[uid] = cached[1]
        else:
            missing.append(uid)

    if not missing:
        return result

    try:
        with httpx.Client(timeout=10) as client:
            token = _fetch_admin_token_sync(client)
            if not token:
                return result
            headers = {"Authorization": f"Bearer {token}"}
            for uid in missing:
                try:
                    res = client.get(
                        f"{settings.keycloak_url}/admin/realms/{settings.keycloak_realm}/users/{uid}",
                        headers=headers,
                    )
                    if res.status_code != 200:
                        continue
                    user = res.json()
                    if user.get("enabled") is False:
                        continue
                    brief = _user_to_brief(user)
                    result[uid] = brief
                    _brief_cache[uid] = (now + _BRIEF_CACHE_TTL, brief)
                except httpx.HTTPError:
                    continue
    except httpx.HTTPError:
        pass

    return result


def find_user_id_by_email(email: str) -> str | None:
    normalized = email.strip().lower()
    if not normalized or "@" not in normalized:
        return None

    try:
        with httpx.Client(timeout=10) as client:
            token_res = client.post(
                f"{settings.keycloak_url}/realms/master/protocol/openid-connect/token",
                data={
                    "grant_type": "password",
                    "client_id": "admin-cli",
                    "username": settings.keycloak_admin_user,
                    "password": settings.keycloak_admin_password,
                },
            )
            token_res.raise_for_status()
            token = token_res.json()["access_token"]
            res = client.get(
                f"{settings.keycloak_url}/admin/realms/{settings.keycloak_realm}/users",
                params={"email": normalized, "exact": "true", "max": 1},
                headers={"Authorization": f"Bearer {token}"},
            )
            if res.status_code != 200:
                return None
            users = res.json()
            if not users:
                return None
            user = users[0]
            if user.get("enabled") is False:
                return None
            return user.get("id")
    except httpx.HTTPError:
        return None
