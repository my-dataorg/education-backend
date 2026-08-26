import logging

import httpx

from app.config import settings

logger = logging.getLogger(__name__)


def _internal_headers() -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    if settings.platform_internal_token:
        headers["X-Internal-Token"] = settings.platform_internal_token
    return headers


def platform_post(path: str, payload: dict) -> bool:
    """Call platform internal API. Returns True on success, False on failure."""
    if not settings.platform_internal_token:
        logger.warning("PLATFORM_INTERNAL_TOKEN not set; skipping platform call to %s", path)
        return False

    url = f"{settings.subscriptions_api_url.rstrip('/')}{path}"
    try:
        with httpx.Client(timeout=10) as client:
            res = client.post(url, json=payload, headers=_internal_headers())
            if res.status_code >= 400:
                logger.warning("Platform POST %s failed: %s %s", path, res.status_code, res.text)
                return False
            return True
    except httpx.HTTPError as exc:
        logger.warning("Platform POST %s error: %s", path, exc)
        return False


def notify_user(
    user_id: str,
    *,
    type: str,
    title: str,
    body: str,
    link: str = "",
) -> bool:
    return platform_post(
        "/internal/notifications",
        {
            "userId": user_id,
            "type": type,
            "title": title,
            "body": body,
            "link": link,
        },
    )


def get_users_brief(user_ids: list[str]) -> dict[str, dict]:
    unique = list(dict.fromkeys(uid for uid in user_ids if uid))
    if not unique or not settings.platform_internal_token:
        return {}
    url = f"{settings.subscriptions_api_url.rstrip('/')}/internal/users/brief"
    try:
        with httpx.Client(timeout=10) as client:
            res = client.post(
                url,
                json={"userIds": unique[:100]},
                headers=_internal_headers(),
            )
            if res.status_code >= 400:
                logger.warning("Platform users brief failed: %s %s", res.status_code, res.text)
                return {}
            items = res.json().get("items") or []
    except (httpx.HTTPError, ValueError):
        logger.warning("Platform users brief error", exc_info=True)
        return {}
    result: dict[str, dict] = {}
    for item in items:
        uid = item.get("userId")
        if not uid:
            continue
        result[uid] = {
            "firstName": (item.get("firstName") or "").strip(),
            "lastName": (item.get("lastName") or "").strip(),
            "displayName": (item.get("displayName") or "").strip(),
            "email": (item.get("email") or "").strip(),
            "username": (item.get("username") or "").strip(),
        }
    return result


def subscribe_user(user_id: str, product_slug: str = "education") -> bool:
    """Auto-subscribe a user to a product. Idempotent; returns False if platform unreachable."""
    return platform_post(
        f"/internal/users/{user_id}/subscriptions",
        {"productSlug": product_slug},
    )
