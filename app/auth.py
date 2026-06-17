import httpx
from fastapi import Depends, Header, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt

from app.config import settings

_bearer = HTTPBearer(auto_error=False)
_jwks_cache: dict | None = None


async def _get_jwks() -> dict:
    global _jwks_cache
    if _jwks_cache:
        return _jwks_cache
    async with httpx.AsyncClient() as client:
        res = await client.get(settings.jwks_url, timeout=10)
        res.raise_for_status()
        _jwks_cache = res.json()
        return _jwks_cache


def _normalize_email(value: str | None) -> str:
    return (value or "").strip().lower()


async def _resolve_email(token: str, payload: dict) -> str:
    for key in ("email", "preferred_username"):
        value = payload.get(key)
        if isinstance(value, str) and "@" in value:
            return _normalize_email(value)

    try:
        async with httpx.AsyncClient() as client:
            res = await client.get(
                f"{settings.issuer}/protocol/openid-connect/userinfo",
                headers={"Authorization": f"Bearer {token}"},
                timeout=10,
            )
            if res.status_code == 200:
                info = res.json()
                for key in ("email", "preferred_username"):
                    value = info.get(key)
                    if isinstance(value, str) and "@" in value:
                        return _normalize_email(value)
    except httpx.HTTPError:
        pass

    return _normalize_email(payload.get("preferred_username"))


async def get_current_user(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
    x_user_email: str | None = Header(None, alias="X-User-Email"),
) -> dict:
    if not creds:
        raise HTTPException(status_code=401, detail="Missing token")
    try:
        jwks = await _get_jwks()
        header = jwt.get_unverified_header(creds.credentials)
        key = next(k for k in jwks["keys"] if k["kid"] == header["kid"])
        payload = jwt.decode(
            creds.credentials,
            key,
            algorithms=[header["alg"]],
            issuer=settings.issuer,
            options={"verify_aud": False},
        )
    except (JWTError, StopIteration, httpx.HTTPError) as e:
        raise HTTPException(status_code=401, detail="Invalid token") from e

    email = await _resolve_email(creds.credentials, payload)
    if x_user_email and "@" in x_user_email:
        email = _normalize_email(x_user_email)

    return {
        "id": payload.get("sub"),
        "email": email,
        "name": payload.get("name") or "User",
        "token": creds.credentials,
    }


async def require_education_subscription(
    user: dict = Depends(get_current_user),
) -> dict:
    async with httpx.AsyncClient() as client:
        res = await client.get(
            f"{settings.subscriptions_api_url}/v1/users/me/subscriptions",
            headers={"Authorization": f"Bearer {user['token']}"},
            timeout=10,
        )
    if res.status_code != 200:
        raise HTTPException(status_code=403, detail="Subscription check failed")
    slugs = {item["productSlug"] for item in res.json().get("items", [])}
    if "education" not in slugs:
        raise HTTPException(status_code=403, detail="Education subscription required")
    return user
