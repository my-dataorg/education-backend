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
