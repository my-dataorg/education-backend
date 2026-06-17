import logging

from sqlalchemy.orm import Session

from app.models import Institute
from app.platform_client import notify_user, subscribe_user as subscribe_user_on_platform
from app.roles import ROLE_LABELS

logger = logging.getLogger(__name__)


def on_member_joined(
    db: Session,
    institute_id: str,
    user_id: str,
    role: str,
    *,
    email: str = "",
) -> None:
    """Auto-subscribe and welcome notification after a user becomes a member."""
    institute = db.get(Institute, institute_id)
    institute_name = institute.name if institute else "an institute"
    role_label = ROLE_LABELS.get(role, role)
    dashboard_link = f"http://localhost:3010/institutes/{institute_id}"

    if not subscribe_user_on_platform(user_id, "education"):
        logger.warning(
            "Auto-subscribe failed for user %s after joining institute %s",
            user_id,
            institute_id,
        )

    notify_user(
        user_id,
        type="education.membership.joined",
        title=f"Welcome to {institute_name}",
        body=f"You joined as {role_label}. Open your institute dashboard to get started.",
        link=dashboard_link,
    )
