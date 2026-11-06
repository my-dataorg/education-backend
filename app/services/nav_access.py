"""Institute nav feature visibility/editability overrides (Owner-configurable)."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.services.institutes import _role_settings, require_membership, require_owner

# Configurable sidebar features (matches education-frontend catalog subset).
CONFIGURABLE_NAV_IDS = (
    "overview",
    "classes",
    "exams",
    "timetable",
    "attendance",
    "fees",
    "reports",
    "calendar",
    "configure",
    "association",
    "class-board",
    "profile",
)

MATRIX_ROLES = ("owner", "admin", "principal", "teacher", "student", "parent")

NavRule = dict[str, bool]  # visible, editable


def _empty_overrides() -> dict[str, dict[str, NavRule]]:
    return {}


def get_nav_access_overrides(db: Session, institute_id: str) -> dict[str, dict[str, NavRule]]:
    settings = _role_settings(db, institute_id)
    raw = settings.nav_access_overrides
    if not raw or not isinstance(raw, dict):
        return _empty_overrides()
    return _sanitize_overrides(raw)


def _sanitize_overrides(raw: dict) -> dict[str, dict[str, NavRule]]:
    out: dict[str, dict[str, NavRule]] = {}
    for feature_id, by_role in raw.items():
        if feature_id not in CONFIGURABLE_NAV_IDS or not isinstance(by_role, dict):
            continue
        role_map: dict[str, NavRule] = {}
        for role, rule in by_role.items():
            if role not in MATRIX_ROLES or not isinstance(rule, dict):
                continue
            visible = rule.get("visible")
            editable = rule.get("editable")
            if visible is None and editable is None:
                continue
            role_map[role] = {
                "visible": bool(visible) if visible is not None else True,
                "editable": bool(editable) if editable is not None else True,
            }
        if role_map:
            out[feature_id] = role_map
    return out


def get_nav_access_matrix(db: Session, institute_id: str, user_id: str) -> dict:
    require_owner(db, institute_id, user_id)
    return {
        "featureIds": list(CONFIGURABLE_NAV_IDS),
        "roles": list(MATRIX_ROLES),
        "overrides": get_nav_access_overrides(db, institute_id),
    }


def get_nav_access_effective(db: Session, institute_id: str, user_id: str) -> dict:
    member = require_membership(db, institute_id, user_id)
    return {
        "role": member.role,
        "overrides": get_nav_access_overrides(db, institute_id),
    }


def update_nav_access_matrix(db: Session, institute_id: str, user_id: str, body) -> dict:
    require_owner(db, institute_id, user_id)
    settings = _role_settings(db, institute_id)
    raw: dict = {}
    for feature_id, by_role in (body.overrides or {}).items():
        if feature_id not in CONFIGURABLE_NAV_IDS:
            continue
        role_map = {}
        for role, rule in (by_role or {}).items():
            if role not in MATRIX_ROLES:
                continue
            role_map[role] = {
                "visible": rule.visible if rule.visible is not None else True,
                "editable": rule.editable if rule.editable is not None else True,
            }
        if role_map:
            raw[feature_id] = role_map
    settings.nav_access_overrides = raw
    db.commit()
    db.refresh(settings)
    return get_nav_access_matrix(db, institute_id, user_id)
