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


def subscribe_user(user_id: str, product_slug: str = "education") -> bool:
    """Auto-subscribe a user to a product. Idempotent; returns False if platform unreachable."""
    return platform_post(
        f"/internal/users/{user_id}/subscriptions",
        {"productSlug": product_slug},
    )
