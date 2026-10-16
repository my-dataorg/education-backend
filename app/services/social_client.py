import logging

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

GUARDIAN_RELATIONSHIP_TYPES = frozenset({"parent_of", "guardian_of"})


def fetch_guardian_children_from_social(guardian_user_id: str, bearer_token: str) -> list[str]:
    """Load linked student user IDs from Social. Returns [] when Social is unavailable."""
    if not settings.social_api_url:
        return []

    url = f"{settings.social_api_url.rstrip('/')}/v1/users/me/relationships"
    try:
        with httpx.Client(timeout=10) as client:
            res = client.get(
                url,
                headers={"Authorization": f"Bearer {bearer_token}"},
                params={"direction": "outgoing"},
            )
            if res.status_code >= 400:
                logger.warning("Social relationships GET failed: %s %s", res.status_code, res.text)
                return []
            payload = res.json()
    except httpx.HTTPError as exc:
        logger.warning("Social relationships GET error: %s", exc)
        return []

    student_ids: list[str] = []
    for edge in payload.get("items", payload if isinstance(payload, list) else []):
        rel_type = edge.get("type") or edge.get("relationshipType")
        if rel_type not in GUARDIAN_RELATIONSHIP_TYPES:
            continue
        target = edge.get("targetUserId") or edge.get("toUserId")
        if isinstance(target, str) and target:
            student_ids.append(target)
    return sorted(set(student_ids))


def write_guardian_cache_stub(guardian_user_id: str, student_ids: list[str]) -> None:
    """Test/dev hook when Social is not configured."""
    _stub_cache[guardian_user_id] = sorted(set(student_ids))


_stub_cache: dict[str, list[str]] = {}


def read_guardian_cache_stub(guardian_user_id: str) -> list[str] | None:
    return _stub_cache.get(guardian_user_id)


def clear_guardian_cache_stub() -> None:
    _stub_cache.clear()
